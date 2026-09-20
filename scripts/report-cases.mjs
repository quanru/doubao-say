import { normalizeJsonControlCharacters } from './omarchy-shell-evidence.mjs';

function allAttemptSteps(attempt) {
  return [
    ...(attempt?.beforeEach ?? []),
    ...(attempt?.steps ?? []),
    ...(attempt?.afterEach ?? []),
  ];
}

function hasScreenshotEvidence(step) {
  return Array.isArray(step?.agentDetails) && step.agentDetails.length > 0;
}

function projectSlug(projectName) {
  const slug = projectName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  if (!slug) {
    throw new Error(
      `Cannot build a preview filename for project ${projectName}`,
    );
  }
  return slug;
}

export function casePreviewFileName(projectName, caseId, extension = 'jpg') {
  if (!/^[a-zA-Z0-9-]+$/.test(caseId)) {
    throw new Error(`Invalid Midscene case ID: ${caseId}`);
  }
  if (!['jpg', 'png', 'webp'].includes(extension)) {
    throw new Error(`Unsupported Midscene screenshot format: ${extension}`);
  }
  return `case-preview-${projectSlug(projectName)}-${caseId}.${extension}`;
}

function scriptAttributes(source) {
  const attributes = new Map();
  for (const match of source.matchAll(/([\w-]+)=["']([^"']*)["']/g)) {
    attributes.set(match[1], match[2]);
  }
  return attributes;
}

function embeddedReportData(reportHtml) {
  const dumps = [];
  const images = new Map();
  for (const match of reportHtml.matchAll(
    /<script\s+([^>]*\btype=["']midscene_web_dump["'][^>]*)>\s*(\{[\s\S]*?)<\/script>/g,
  )) {
    const attributes = scriptAttributes(match[1]);
    dumps.push({
      reportId:
        attributes.get('data-report-id') ??
        attributes.get('data-group-id') ??
        null,
      dump: JSON.parse(normalizeJsonControlCharacters(match[2].trim())),
    });
  }
  for (const match of reportHtml.matchAll(
    /<script\s+type=["']midscene-image["']\s+data-id=["']([^"']+)["'][^>]*>\s*data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)\s*<\/script>/g,
  )) {
    images.set(match[1], {
      extension: match[2] === 'jpeg' ? 'jpg' : match[2],
      bytes: Buffer.from(match[3], 'base64'),
    });
  }
  return { dumps, images };
}

function normalizedText(value) {
  if (typeof value !== 'string') return null;
  const text = value
    .replaceAll('__midscene_lt__', '<')
    .replaceAll('__midscene_gt__', '>')
    .replace(/\s+/g, ' ')
    .trim();
  return text || null;
}

function taggedModelText(rawResponse) {
  const response = normalizedText(rawResponse);
  if (!response) return null;
  const tagged = response.match(
    /<(?:observation|planning)>([\s\S]*?)<\/(?:observation|planning)>/,
  );
  return normalizedText(tagged?.[1]);
}

function modelTaskText(task) {
  return (
    normalizedText(task?.thought) ??
    normalizedText(task?.log?.taskInfo?.formatResponse?.thought) ??
    normalizedText(task?.output?.thought) ??
    taggedModelText(task?.log?.rawResponse) ??
    taggedModelText(task?.log?.taskInfo?.rawResponse) ??
    normalizedText(task?.output?.output)
  );
}

function isModelTask(task) {
  return (
    task?.type === 'Insight' ||
    (task?.type === 'Planning' && task?.subType === 'Plan')
  );
}

function executionForDetail(dumps, detail) {
  const preferred = dumps.filter(
    (entry) => !detail.reportId || entry.reportId === detail.reportId,
  );
  for (const entry of preferred.length ? preferred : dumps) {
    const execution = entry.dump?.executions?.find(
      (item) => item.id === detail.executionId,
    );
    if (execution) return execution;
  }
  return null;
}

function evidenceForStep(step, embedded) {
  const candidates = [];
  for (const detail of step.agentDetails ?? []) {
    const execution = executionForDetail(embedded.dumps, detail);
    for (const task of execution?.tasks ?? []) {
      const screenshotId = task?.uiContext?.screenshot?.id;
      const explanation = modelTaskText(task);
      if (
        isModelTask(task) &&
        screenshotId &&
        embedded.images.has(screenshotId)
      ) {
        candidates.push({ screenshotId, explanation });
      }
    }
  }
  const selected = candidates.at(-1);
  if (!selected) {
    throw new Error(`Step ${step.id} has no embedded node screenshot`);
  }
  const error = normalizedText(step.error?.message);
  const result = normalizedText(step.output?.summary);
  const description = error ?? selected.explanation ?? result;
  if (!description) {
    throw new Error(`Step ${step.id} has no AI response or error text`);
  }
  return {
    screenshot: embedded.images.get(selected.screenshotId),
    description,
    descriptionKind: error ? 'error' : selected.explanation ? 'ai' : 'result',
  };
}

export function reportCases(run, projectName, { reportHtml } = {}) {
  const project = run?.projects?.find((item) => item.name === projectName);
  if (!project) {
    throw new Error(`Project ${projectName} is absent from the runner dump`);
  }

  const embedded = reportHtml ? embeddedReportData(reportHtml) : null;
  return (project.documents ?? []).flatMap((document) =>
    (document.cases ?? []).map((testCase) => {
      const attempt = testCase.attempts?.at(-1);
      if (!attempt) {
        throw new Error(
          `Case ${testCase.name ?? testCase.caseId} has no attempt`,
        );
      }
      const steps = allAttemptSteps(attempt);
      const passed = (testCase.status ?? attempt.status) === 'success';
      const step = passed
        ? steps.findLast(hasScreenshotEvidence) ?? steps.at(-1)
        : steps.find(
            (item) => item.status === 'failed' && hasScreenshotEvidence(item),
          ) ??
          steps.find((item) => item.status === 'failed');
      if (!step?.id) {
        throw new Error(
          `Case ${testCase.name ?? testCase.caseId} has no report step to preview`,
        );
      }
      if (!testCase.caseId || !testCase.name) {
        throw new Error('Midscene case metadata is incomplete');
      }
      const evidence = embedded ? evidenceForStep(step, embedded) : null;
      return {
        caseId: testCase.caseId,
        name: testCase.name,
        status: passed ? 'success' : 'failed',
        stepId: step.id,
        stepTitle: step.title ?? step.node,
        selection: passed ? 'last-screenshot' : 'first-failing-screenshot',
        previewFile: casePreviewFileName(
          projectName,
          testCase.caseId,
          evidence?.screenshot.extension,
        ),
        ...(evidence ?? {}),
      };
    }),
  );
}
