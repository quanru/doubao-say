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

export function casePreviewFileName(projectName, caseId) {
  if (!/^[a-zA-Z0-9-]+$/.test(caseId)) {
    throw new Error(`Invalid Midscene case ID: ${caseId}`);
  }
  return `case-preview-${projectSlug(projectName)}-${caseId}.jpg`;
}

export function reportCases(run, projectName) {
  const project = run?.projects?.find((item) => item.name === projectName);
  if (!project) {
    throw new Error(`Project ${projectName} is absent from the runner dump`);
  }

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
      return {
        caseId: testCase.caseId,
        name: testCase.name,
        status: passed ? 'success' : 'failed',
        stepId: step.id,
        stepTitle: step.title ?? step.node,
        selection: passed ? 'last-screenshot' : 'first-failing-screenshot',
        previewFile: casePreviewFileName(projectName, testCase.caseId),
      };
    }),
  );
}
