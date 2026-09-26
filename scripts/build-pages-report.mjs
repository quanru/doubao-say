#!/usr/bin/env node

import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {
  findHtmlFiles,
  reportDumps,
  testRunDump,
} from './omarchy-shell-evidence.mjs';
import { reportCases } from './report-cases.mjs';

const MANIFEST_VERSION = 7;
const SUPPORTED_MANIFEST_VERSIONS = new Set([
  1,
  2,
  3,
  4,
  5,
  6,
  MANIFEST_VERSION,
]);

export function formatDuration(durationMs) {
  if (!Number.isFinite(durationMs) || durationMs < 0) return '';
  const totalSeconds = Math.round(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m${String(seconds).padStart(2, '0')}s`;
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined) {
      throw new Error(`Invalid argument near ${key ?? '<end>'}`);
    }
    options[key.slice(2)] = value;
  }
  return options;
}

function required(options, name) {
  const value = options[name];
  if (!value) {
    throw new Error(`Missing --${name}`);
  }
  return value;
}

function parseReportGroups(options) {
  if (!options['report-groups']) return null;
  let groups;
  try {
    groups = JSON.parse(options['report-groups']);
  } catch (error) {
    throw new Error(`Invalid --report-groups JSON: ${error.message}`);
  }
  if (
    !Array.isArray(groups) ||
    groups.length === 0 ||
    groups.some(
      (group) =>
        !['primary', 'auxiliary'].includes(group.role) ||
        typeof group.label !== 'string' ||
        !Array.isArray(group.projects) ||
        group.projects.length === 0 ||
        group.projects.some(
          (project) =>
            typeof project !== 'string' || !/^[a-z0-9-]+$/.test(project),
        ),
    )
  ) {
    throw new Error('--report-groups must describe labeled project groups');
  }
  const projects = groups.flatMap((group) => group.projects);
  if (new Set(projects).size !== projects.length) {
    throw new Error('--report-groups cannot contain duplicate projects');
  }
  return groups;
}

function projectSlug(project) {
  const slug = project
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  if (!slug) throw new Error(`Cannot build a filename for project ${project}`);
  return slug;
}

async function findUniqueFile(directory, basename) {
  const matches = [];
  async function visit(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const item = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(item);
      else if (entry.isFile() && entry.name === basename) matches.push(item);
    }
  }
  await visit(directory);
  if (matches.length !== 1) {
    throw new Error(
      `Expected one ${basename} in the report bundle, found ${matches.length}`,
    );
  }
  return matches[0];
}

function validateRunId(value) {
  if (!/^\d+$/.test(value)) {
    throw new Error('Run ID must contain digits only');
  }
  return value;
}

function validateRetention(value) {
  const retention = Number(value);
  if (!Number.isInteger(retention) || retention < 1 || retention > 50) {
    throw new Error('Report retention must be an integer from 1 to 50');
  }
  return retention;
}

function normalizeBaseUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error('Pages URL must use HTTP or HTTPS');
  }
  if (!url.pathname.endsWith('/')) {
    url.pathname += '/';
  }
  return url;
}

function collectModelUsage(reportHtml) {
  const calls = new Map();

  function visit(value) {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== 'object') {
      return;
    }
    const usage = value.usage;
    if (usage && typeof usage === 'object') {
      const callId = usage._midscene_call_id;
      if (typeof callId === 'string' && !calls.has(callId)) {
        calls.set(callId, {
          durationMs: Number.isFinite(usage.time_cost) ? usage.time_cost : null,
          tokens: Number.isFinite(usage.total_tokens)
            ? usage.total_tokens
            : null,
        });
      }
    }
    Object.values(value).forEach(visit);
  }

  for (const dump of reportDumps(reportHtml)) visit(dump);

  const durations = [...calls.values()]
    .map((call) => call.durationMs)
    .filter((duration) => duration !== null);
  const tokens = [...calls.values()]
    .map((call) => call.tokens)
    .filter((tokenCount) => tokenCount !== null);
  return {
    modelCallCount: calls.size,
    averageDurationMs: durations.length
      ? Math.round(
          durations.reduce((sum, duration) => sum + duration, 0) /
            durations.length,
        )
      : null,
    tokenUsage: tokens.length
      ? tokens.reduce((sum, tokenCount) => sum + tokenCount, 0)
      : null,
  };
}

function collectAssertionResults(run) {
  let passed = 0;
  let total = 0;
  for (const project of run?.projects ?? []) {
    for (const document of project.documents ?? []) {
      for (const testCase of document.cases ?? []) {
        const attempt = testCase.attempts?.at(-1);
        if (!attempt) continue;
        for (const step of [
          ...(attempt.beforeEach ?? []),
          ...(attempt.steps ?? []),
          ...(attempt.afterEach ?? []),
        ]) {
          if (step.node !== 'aiAssert') continue;
          total += 1;
          if (step.status === 'success') passed += 1;
        }
      }
    }
  }
  return { passed, total };
}

async function buildReportEntry({
  includeCaseReportPath = false,
  label,
  previewPath,
  project,
  report,
  reportPath,
  role,
}) {
  const status = report.run?.status ?? 'unknown';
  const cases = (
    await reportCases(report.run, project, {
      reportHtml: report.html,
      reportFile: report.file,
    })
  ).map((testCase) => ({
    caseId: testCase.caseId,
    name: testCase.name,
    status: testCase.status,
    ...(Number.isFinite(testCase.durationMs)
      ? { durationMs: testCase.durationMs }
      : {}),
    stepId: testCase.stepId,
    selection: testCase.selection,
    description: testCase.description,
    descriptionKind: testCase.descriptionKind,
    ...(testCase.previewFile
      ? {
          previewPath: `${path.posix.dirname(reportPath)}/${testCase.previewFile}`,
        }
      : {}),
    ...(includeCaseReportPath ? { reportPath } : {}),
  }));
  return {
    role,
    project,
    label,
    status,
    previewStep: status === 'success' ? 'last' : 'last-error',
    reportPath,
    previewPath,
    scenarios: {
      passed: report.run?.summary?.passed ?? 0,
      total: report.run?.summary?.total ?? 0,
    },
    assertions: collectAssertionResults(report.run),
    cases,
  };
}

async function buildReportGroup({ label, reports, role }) {
  const reportEntries = await Promise.all(
    reports.map((item) =>
      item.fallbackEntry ??
      buildReportEntry({
        ...item,
        includeCaseReportPath: true,
        label,
        role,
      }),
    ),
  );
  const sum = (field, nested) =>
    reportEntries.reduce((total, entry) => total + entry[field][nested], 0);
  const status = reportEntries.every((entry) => entry.status === 'success')
    ? 'success'
    : 'failed';
  return {
    role,
    projects: reportEntries.map((entry) => entry.project),
    label,
    status,
    previewStep: status === 'success' ? 'last' : 'last-error',
    reports: reportEntries.map((entry) => ({
      project: entry.project,
      status: entry.status,
      previewStep: entry.previewStep,
      reportPath: entry.reportPath,
      previewPath: entry.previewPath,
    })),
    scenarios: {
      passed: sum('scenarios', 'passed'),
      total: sum('scenarios', 'total'),
    },
    assertions: {
      passed: sum('assertions', 'passed'),
      total: sum('assertions', 'total'),
    },
    cases: reportEntries.flatMap((entry) => entry.cases),
  };
}

function fallbackDescription(project, status) {
  const result = status?.result;
  const stage = status?.stage;
  if (result && stage) {
    return `${project} stopped during ${stage} (${result}) before Midscene produced a native report.`;
  }
  return `${project} did not produce a native Midscene report. Open the Actions run for the failing setup or test step.`;
}

function buildFallbackEntry({ label, project, reportPrefix, role, status }) {
  const slug = projectSlug(project);
  const reportPath = `${reportPrefix}/shard-failure-${slug}.html`;
  const previewPath = `${reportPrefix}/shard-failure-${slug}.svg`;
  const description = fallbackDescription(project, status);
  return {
    role,
    project,
    label,
    status: 'failed',
    previewStep: 'last-error',
    reportPath,
    previewPath,
    scenarios: { passed: 0, total: 1 },
    assertions: { passed: 0, total: 0 },
    cases: [
      {
        caseId: `infrastructure-${slug}`,
        name: `${project} CI shard`,
        status: 'failed',
        selection: 'workflow-failure',
        description,
        descriptionKind: 'error',
        previewPath,
        reportPath,
      },
    ],
  };
}

function fallbackSvg(project, description) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#160d12"/>
  <rect x="70" y="70" width="1060" height="535" rx="28" fill="#26151d" stroke="#ef4444" stroke-width="4"/>
  <text x="120" y="175" fill="#fca5a5" font-family="system-ui,sans-serif" font-size="34" font-weight="700">CI shard failed before report capture</text>
  <text x="120" y="255" fill="#ffffff" font-family="system-ui,sans-serif" font-size="30">${escapeHtml(project)}</text>
  <foreignObject x="120" y="305" width="960" height="210"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#d1d5db;font:26px/1.5 system-ui,sans-serif">${escapeHtml(description)}</div></foreignObject>
</svg>\n`;
}

function fallbackHtml(project, description, workflowUrl) {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${escapeHtml(project)} · CI failure</title></head><body style="font-family:system-ui,sans-serif;max-width:850px;margin:4rem auto;padding:0 1rem"><h1>CI shard failed before report capture</h1><h2>${escapeHtml(project)}</h2><p>${escapeHtml(description)}</p><p><a href="${escapeHtml(workflowUrl)}">Open the GitHub Actions run</a></p></body></html>\n`;
}

async function shardStatuses(directory) {
  const statuses = new Map();
  async function visit(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const item = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(item);
      else if (entry.isFile() && /^ci-shard-status-.+\.json$/.test(entry.name)) {
        const status = JSON.parse(await readFile(item, 'utf8'));
        if (typeof status.project !== 'string') {
          throw new Error(`${item} does not identify a project`);
        }
        statuses.set(status.project, status);
      }
    }
  }
  await visit(directory);
  return statuses;
}

function validReportEntry(entry, files) {
  const legacyReport =
    typeof entry.project === 'string' &&
    typeof entry.reportPath === 'string' &&
    typeof entry.previewPath === 'string' &&
    files?.includes(entry.reportPath) &&
    files?.includes(entry.previewPath);
  const shardedReport =
    Array.isArray(entry.projects) &&
    entry.projects.length > 0 &&
    entry.projects.every((project) => typeof project === 'string') &&
    Array.isArray(entry.reports) &&
    entry.reports.length === entry.projects.length &&
    entry.reports.every(
      (report) =>
        typeof report.project === 'string' &&
        typeof report.status === 'string' &&
        ['last', 'last-error'].includes(report.previewStep) &&
        files?.includes(report.reportPath) &&
        files?.includes(report.previewPath),
    );
  return (
    ['primary', 'auxiliary'].includes(entry.role) &&
    typeof entry.label === 'string' &&
    typeof entry.status === 'string' &&
    ['last', 'last-error'].includes(entry.previewStep) &&
    (legacyReport || shardedReport) &&
    Number.isInteger(entry.scenarios?.passed) &&
    Number.isInteger(entry.scenarios?.total) &&
    Number.isInteger(entry.assertions?.passed) &&
    Number.isInteger(entry.assertions?.total) &&
    (entry.cases === undefined ||
      (Array.isArray(entry.cases) &&
        entry.cases.every(
          (testCase) =>
            typeof testCase.caseId === 'string' &&
            typeof testCase.name === 'string' &&
            ['success', 'failed'].includes(testCase.status) &&
            (testCase.durationMs === undefined ||
              Number.isInteger(testCase.durationMs)) &&
            (typeof testCase.stepId === 'string' ||
              testCase.selection === 'workflow-failure') &&
            [
              'last-screenshot',
              'first-failing-screenshot',
              'first-failing-no-screenshot',
              'workflow-failure',
            ].includes(testCase.selection) &&
            (testCase.description === undefined ||
              (typeof testCase.description === 'string' &&
                testCase.description.length > 0)) &&
            (testCase.descriptionKind === undefined ||
              ['ai', 'error', 'result'].includes(testCase.descriptionKind)) &&
            (testCase.description === undefined) ===
              (testCase.descriptionKind === undefined) &&
            (testCase.selection === 'first-failing-no-screenshot'
              ? testCase.previewPath === undefined
              : files?.includes(testCase.previewPath)) &&
            (testCase.reportPath === undefined ||
              files?.includes(testCase.reportPath)),
        )))
  );
}

function validateHistoryManifest(manifest) {
  if (
    !manifest ||
    !SUPPORTED_MANIFEST_VERSIONS.has(manifest.version) ||
    !Array.isArray(manifest.reports)
  ) {
    throw new Error('Existing Pages manifest has an unsupported shape');
  }
  for (const report of manifest.reports) {
    if (
      typeof report.runId !== 'string' ||
      !/^\d+$/.test(report.runId) ||
      report.reportPath !== `reports/${report.runId}/index.html` ||
      typeof report.workflowUrl !== 'string' ||
      (report.files !== undefined &&
        (!Array.isArray(report.files) ||
          report.files.some(
            (file) =>
              typeof file !== 'string' ||
              !/^reports\/\d+\/(?:screenshots\/)?[a-z0-9.-]+$/.test(file) ||
              !file.startsWith(`reports/${report.runId}/`),
          ))) ||
      (report.entries !== undefined &&
        (!Array.isArray(report.entries) ||
          report.entries.some((entry) => !validReportEntry(entry, report.files))))
    ) {
      throw new Error(
        'Existing Pages manifest contains an invalid report entry',
      );
    }
  }
  return manifest;
}

async function fetchHistory(baseUrl) {
  const manifestUrl = new URL('reports/manifest.json', baseUrl);
  const response = await fetch(manifestUrl, { redirect: 'follow' });
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(
      `Cannot download existing manifest: HTTP ${response.status}`,
    );
  }
  let manifest;
  try {
    manifest = await response.json();
  } catch (error) {
    throw new Error(`Cannot parse existing manifest: ${error.message}`);
  }
  return validateHistoryManifest(manifest).reports;
}

async function restoreReport(baseUrl, siteDirectory, report) {
  const files = report.files ?? [report.reportPath];
  let nextFile = 0;
  let failure;
  async function restoreNextFiles() {
    while (nextFile < files.length && !failure) {
      const file = files[nextFile++];
      try {
        await restoreFile(baseUrl, siteDirectory, report, file);
      } catch (error) {
        failure ??= error;
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(4, files.length) }, () => restoreNextFiles()),
  );
  if (failure) throw failure;
}

async function restoreFile(baseUrl, siteDirectory, report, file) {
  let response;
  for (let attempt = 0; attempt < 6; attempt++) {
    response = await fetch(new URL(file, baseUrl), {
      redirect: 'follow',
      signal: AbortSignal.timeout(30_000),
    });
    const retryable =
      (response.status === 503 && attempt < 2) ||
      (response.status === 429 && attempt < 5);
    if (!retryable) break;
    const retryAfterHeader = response.headers.get('retry-after');
    const retryAfter = Number(retryAfterHeader);
    const delayMs =
      response.status === 429
        ? retryAfterHeader !== null && Number.isFinite(retryAfter) && retryAfter >= 0
          ? Math.min(retryAfter * 1000, 30_000)
          : Math.min(1000 * 2 ** (attempt + 1), 30_000)
        : 1000 * (attempt + 1);
    await response.body?.cancel();
    await new Promise((done) => setTimeout(done, delayMs));
  }
  if (!response.ok) {
    throw new Error(
      `Cannot restore report for run ${report.runId}: HTTP ${response.status}`,
    );
  }
  const contentType = response.headers.get('content-type') ?? '';
  if (
    file.endsWith('.html') &&
    !contentType.toLowerCase().includes('text/html')
  ) {
    throw new Error(
      `Cannot restore report for run ${report.runId}: expected text/html, got ${contentType || 'no Content-Type'}`,
    );
  }
  const destination = path.join(siteDirectory, file);
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, Buffer.from(await response.arrayBuffer()));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatModelDuration(durationMs) {
  if (durationMs === null) return 'Unavailable';
  return `${(durationMs / 1000).toFixed(2)} s`;
}

function runStepHref(entry, testCase) {
  const reportPath = testCase.reportPath ?? entry.reportPath;
  if (!testCase.stepId) return path.basename(reportPath);
  return `${path.basename(reportPath)}#${new URLSearchParams({
    'runner-step': testCase.stepId,
  })}`;
}

function nativeReportLinks(entry) {
  const reports = entry.reports ?? [entry];
  return reports
    .map((report, index) => {
      const suffix = reports.length > 1 ? ` ${index + 1}` : '';
      return `<a class="native-report" href="${escapeHtml(path.basename(report.reportPath))}">Open native Midscene report${suffix} →</a>`;
    })
    .join(' ');
}

function buildRunIndex(report) {
  const sections = report.entries
    .map((entry) => {
      const rows = entry.cases
        .map((testCase) => {
          const target = runStepHref(entry, testCase);
          const image = testCase.previewPath
            ? path.basename(testCase.previewPath)
            : null;
          const status = testCase.status === 'success' ? '✅ Passed' : '❌ Failed';
          const descriptionLabel = {
            ai: 'AI',
            error: 'Error',
            result: 'Result',
          }[testCase.descriptionKind];
          return `
            <tr>
              <td class="status">${status}</td>
              <td><a href="${escapeHtml(target)}">${escapeHtml(testCase.name)}</a></td>
              <td class="duration">${escapeHtml(formatDuration(testCase.durationMs))}</td>
              <td>${image ? `<a href="${escapeHtml(target)}"><img src="${escapeHtml(image)}" alt="${escapeHtml(testCase.name)} node screenshot" loading="lazy"></a>` : '<span class="unavailable">Not available</span>'}</td>
              <td><strong>${escapeHtml(descriptionLabel)}:</strong> ${escapeHtml(testCase.description)}</td>
            </tr>`;
        })
        .join('');
      return `
        <section>
          <div class="section-heading">
            <div>
              <h2>${escapeHtml(entry.label)}</h2>
              <p>${entry.scenarios.passed}/${entry.scenarios.total} cases passed</p>
            </div>
            <div>${nativeReportLinks(entry)}</div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Result</th><th>Case</th><th>Duration</th><th>Node screenshot</th><th>AI response / error</th></tr></thead>
              <tbody>${rows}
              </tbody>
            </table>
          </div>
        </section>`;
    })
    .join('');

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${escapeHtml(report.label)} · Midscene E2E evidence</title>
    <style>
      :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
      body { margin: 0 auto; max-width: 1500px; padding: 2rem 1rem 4rem; }
      header { margin-bottom: 2rem; }
      h1, h2 { margin: 0; }
      p { color: #777; margin: .35rem 0 0; }
      section { margin-top: 2rem; }
      .section-heading { align-items: end; display: flex; gap: 1rem; justify-content: space-between; margin-bottom: .75rem; }
      .native-report, a { color: #2878d0; }
      .table-wrap { overflow-x: auto; }
      table { border-collapse: collapse; table-layout: fixed; width: 100%; }
      th, td { border-bottom: 1px solid #8885; padding: .8rem; text-align: left; vertical-align: top; }
      th { font-size: .78rem; text-transform: uppercase; }
      th:nth-child(1) { width: 7rem; }
      th:nth-child(2) { width: 17rem; }
      th:nth-child(3) { width: 6rem; }
      th:nth-child(4) { width: 34%; }
      td { line-height: 1.45; }
      td.status, td.duration { white-space: nowrap; }
      img { border: 1px solid #8885; border-radius: .5rem; display: block; height: auto; width: 100%; }
      @media (max-width: 900px) {
        body { padding: 1rem .6rem 3rem; }
        .section-heading { align-items: start; flex-direction: column; }
        table { min-width: 980px; }
      }
    </style>
  </head>
  <body>
    <header>
      <h1>${escapeHtml(report.label)} × Midscene</h1>
      <p>Run ${escapeHtml(report.runId)} · ${escapeHtml(report.successRate.toFixed(1))}% passed · <a href="${escapeHtml(report.workflowUrl)}">GitHub Actions</a> · <a href="../../">Report history</a></p>
      <p>Each image is the original page screenshot used by that node. Click a case or image to open the exact Midscene step and Agent replay.</p>
    </header>
    <main>${sections}
    </main>
  </body>
</html>
`;
}

function buildIndex(reports) {
  const rows = reports
    .map(
      (report) => `
          <tr>
            <td><a href="${escapeHtml(report.workflowUrl)}">${escapeHtml(report.runId)}</a></td>
            <td>${escapeHtml(report.label ?? 'Midscene E2E')}</td>
            <td>${escapeHtml(report.generatedAt)}</td>
            <td>${escapeHtml(report.successRate.toFixed(1))}%</td>
            <td>${escapeHtml(formatModelDuration(report.averageDurationMs))}</td>
            <td>${escapeHtml(report.modelCallCount)}</td>
            <td>${report.tokenUsage === null ? 'Unavailable' : escapeHtml(report.tokenUsage.toLocaleString('en-US'))}</td>
            <td><a href="${escapeHtml(report.workflowUrl)}">Actions run</a></td>
            <td><a href="${escapeHtml(report.reportPath)}">HTML report</a></td>
          </tr>`,
    )
    .join('');

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Doubao Say test report history</title>
    <style>
      :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
      body { margin: 0 auto; max-width: 1180px; padding: 2rem 1rem; }
      h1 { margin-bottom: .4rem; }
      p { color: #777; margin-top: 0; }
      .table-wrap { overflow-x: auto; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border-bottom: 1px solid #8885; padding: .75rem; text-align: left; white-space: nowrap; }
      th { font-size: .82rem; text-transform: uppercase; }
      a { color: #2878d0; }
    </style>
  </head>
  <body>
    <main>
      <h1>Doubao Say test report history</h1>
      <p>Midscene CI reports, newest first.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Run ID</th><th>Distribution</th><th>Generated (UTC)</th><th>Success rate</th><th>Avg. model call</th><th>Model calls</th><th>Tokens</th><th>Workflow</th><th>Report</th></tr></thead>
          <tbody>${rows}
          </tbody>
        </table>
      </div>
    </main>
  </body>
</html>
`;
}

export async function buildPagesReport(options) {
  const reportDirectory = path.resolve(required(options, 'report-dir'));
  const siteDirectory = path.resolve(required(options, 'site-dir'));
  const runId = validateRunId(required(options, 'run-id'));
  const workflowUrl = required(options, 'workflow-url');
  const generatedAt = new Date(required(options, 'generated-at')).toISOString();
  const retention = validateRetention(required(options, 'retention'));
  const baseUrl = normalizeBaseUrl(required(options, 'pages-url'));
  const label = options.label || 'Midscene E2E';
  const reportGroups = parseReportGroups(options);
  const primaryProject = reportGroups
    ? null
    : required(options, 'primary-project');
  const primaryReportLabel = options['primary-report-label'] || 'Doubao Say';
  const auxiliaryProject = reportGroups ? null : options['auxiliary-project'];
  const auxiliaryReportLabel = reportGroups
    ? null
    : options['auxiliary-report-label'];
  if (
    !reportGroups &&
    Boolean(auxiliaryProject) !== Boolean(auxiliaryReportLabel)
  ) {
    throw new Error(
      '--auxiliary-project and --auxiliary-report-label must be provided together',
    );
  }

  const existingItems = await readdir(siteDirectory).catch((error) => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (existingItems?.length) {
    throw new Error('Site output directory must be empty');
  }

  const reportCandidates = (
    await Promise.all(
      (await findHtmlFiles(reportDirectory)).map(async (file) => ({
        file,
        html: await readFile(file, 'utf8'),
      })),
    )
  ).map((report) => ({
    ...report,
    run: testRunDump(report.html),
  }))
    // Midscene Test 1.13.0 writes its HTML to midscene-e2e-<run>/ instead of
    // the legacy test-run-* location, so findHtmlFiles also returns the
    // standalone computer-*.html agent reports. Those carry no runner dump;
    // only Midscene Test reports participate in aggregation.
    .filter((report) => report.run !== null);
  const latestByProject = new Map();
  for (const report of reportCandidates) {
    report.startedAt = Date.parse(report.run?.startedAt ?? '') || 0;
    const projectKey = report.run?.projects
      ?.map((project) => project.name)
      .join(',');
    if (!projectKey) continue;
    const previous = latestByProject.get(projectKey);
    if (!previous || report.startedAt >= previous.startedAt) {
      latestByProject.set(projectKey, report);
    }
  }
  const htmlReports = [...latestByProject.values()].sort(
    (left, right) => left.startedAt - right.startedAt,
  );
  const reportForProject = (projectName) =>
    htmlReports.find(
      (report) =>
        report.run?.projects?.length === 1 &&
        report.run.projects[0].name === projectName,
    );
  const reportPrefix = `reports/${runId}`;
  const statuses = await shardStatuses(reportDirectory);
  const generatedFallbacks = [];
  let selectedReports;
  let entries;
  let baseFiles;
  let reportCopies;
  if (reportGroups) {
    const groupedReports = reportGroups.map((group) => ({
      ...group,
      reports: group.projects.map((project) => {
        const report = reportForProject(project);
        const status = statuses.get(project);
        if (
          !report ||
          (status?.captureOutcome && status.captureOutcome !== 'success')
        ) {
          const fallbackEntry = buildFallbackEntry({
            label: group.label,
            project,
            reportPrefix,
            role: group.role,
            status,
          });
          generatedFallbacks.push({ project, entry: fallbackEntry });
          return { project, fallbackEntry };
        }
        const slug = projectSlug(project);
        return {
          project,
          report,
          reportPath: `${reportPrefix}/native-report-${slug}.html`,
          previewPath: `${reportPrefix}/report-preview-${slug}.png`,
        };
      }),
    }));
    selectedReports = groupedReports.flatMap((group) =>
      group.reports.map((item) => item.report).filter(Boolean),
    );
    entries = await Promise.all(
      groupedReports.map((group) => buildReportGroup(group)),
    );
    reportCopies = groupedReports.flatMap((group) =>
      group.reports.filter((item) => item.report).flatMap((item) => [
        {
          source: item.report.file,
          destination: path.basename(item.reportPath),
        },
        {
          sourceName: path.basename(item.previewPath),
          destination: path.basename(item.previewPath),
        },
      ]),
    );
    baseFiles = [
      `${reportPrefix}/index.html`,
      ...entries.flatMap((entry) =>
        entry.reports.flatMap((report) => [
          report.reportPath,
          report.previewPath,
        ]),
      ),
    ];
  } else {
    const primaryReport = reportForProject(primaryProject);
    if (!primaryReport) {
      throw new Error(
        `No Midscene Test report found for project ${primaryProject}`,
      );
    }
    const auxiliaryReport = auxiliaryProject
      ? reportForProject(auxiliaryProject)
      : null;
    selectedReports = [primaryReport, auxiliaryReport].filter(Boolean);
    const primaryNativeReport = `${reportPrefix}/native-report.html`;
    const auxiliaryNativeReport = `${reportPrefix}/auxiliary-report.html`;
    baseFiles = auxiliaryReport
      ? [
          'index.html',
          'native-report.html',
          'auxiliary-report.html',
          'report-preview.png',
          'auxiliary-report-preview.png',
        ].map((name) => `${reportPrefix}/${name}`)
      : [
          `${reportPrefix}/index.html`,
          primaryNativeReport,
          `${reportPrefix}/report-preview.png`,
        ];
    entries = await Promise.all(
      [
        buildReportEntry({
          role: 'primary',
          project: primaryProject,
          label: primaryReportLabel,
          report: primaryReport,
          reportPath: primaryNativeReport,
          previewPath: `${reportPrefix}/report-preview.png`,
        }),
        ...(auxiliaryReport
          ? [
              buildReportEntry({
                role: 'auxiliary',
                project: auxiliaryProject,
                label: auxiliaryReportLabel,
                report: auxiliaryReport,
                reportPath: auxiliaryNativeReport,
                previewPath: `${reportPrefix}/auxiliary-report-preview.png`,
              }),
            ]
          : []),
      ],
    );
    reportCopies = [
      {
        source: primaryReport.file,
        destination: 'native-report.html',
      },
      {
        sourceName: 'report-preview.png',
        destination: 'report-preview.png',
      },
      ...(auxiliaryReport
        ? [
            {
              source: auxiliaryReport.file,
              destination: 'auxiliary-report.html',
            },
            {
              sourceName: 'auxiliary-report-preview.png',
              destination: 'auxiliary-report-preview.png',
            },
          ]
        : []),
    ];
  }
  const selectedFiles = new Set(selectedReports.map((report) => report.file));
  // Midscene 1.13.0 keeps native-report screenshots in a sibling
  // screenshots/ directory instead of inlining them in the HTML. The
  // published native reports load screenshots/<id>.jpeg relatively, so
  // publish the directory next to the flattened report files. File names are
  // screenshot UUIDs (content-addressed), so a name shared by reports is
  // published once.
  const screenshotCopies = [];
  const seenScreenshotNames = new Set();
  for (const report of selectedReports) {
    const screenshotDirectory = path.join(
      path.dirname(report.file),
      'screenshots',
    );
    let screenshotNames = [];
    try {
      screenshotNames = await readdir(screenshotDirectory);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      continue;
    }
    for (const name of screenshotNames.sort()) {
      if (seenScreenshotNames.has(name)) continue;
      seenScreenshotNames.add(name);
      screenshotCopies.push({
        source: path.join(screenshotDirectory, name),
        destination: `screenshots/${name}`,
      });
    }
  }
  reportCopies.push(...screenshotCopies);
  const declaredProjects = new Set(
    reportGroups ? reportGroups.flatMap((group) => group.projects) : [],
  );
  const unexpectedProjects = htmlReports
    .filter(
      (report) =>
        !selectedFiles.has(report.file) &&
        !report.run?.projects?.every((project) =>
          declaredProjects.has(project.name),
        ),
    )
    .flatMap((report) =>
      report.run?.projects?.map((project) => project.name) ?? [path.basename(report.file)],
    );
  if (unexpectedProjects.length) {
    throw new Error(
      `Unexpected Midscene Test project(s): ${unexpectedProjects.join(', ')}`,
    );
  }
  const usage = collectModelUsage(
    selectedReports.map((report) => report.html).join('\n'),
  );
  const result = selectedReports.reduce(
    (total, report) => ({
      passed: total.passed + (report.run?.summary?.passed ?? 0),
      tests: total.tests + (report.run?.summary?.total ?? 0),
    }),
    { passed: 0, tests: 0 },
  );
  const casePreviewFiles = entries.flatMap((entry) =>
    entry.cases.map((testCase) => testCase.previewPath).filter(Boolean),
  );
  const screenshotFiles = screenshotCopies.map(
    (copy) => `${reportPrefix}/${copy.destination}`,
  );
  const files = [
    ...new Set([...baseFiles, ...casePreviewFiles, ...screenshotFiles]),
  ];
  const current = {
    runId,
    generatedAt,
    label,
    successRate: result.tests
      ? Math.round((result.passed / result.tests) * 100)
      : 0,
    testCount: result.tests,
    ...usage,
    workflowUrl,
    reportPath: `reports/${runId}/index.html`,
    files,
    entries,
  };

  const history = (await fetchHistory(baseUrl))
    .filter((report) => report.runId !== runId)
    .slice(0, retention - 1);

  await mkdir(siteDirectory, { recursive: true });
  for (const report of history) {
    await restoreReport(baseUrl, siteDirectory, report);
  }

  const currentDirectory = path.join(siteDirectory, reportPrefix);
  await mkdir(currentDirectory, { recursive: true });
  for (const reportCopy of reportCopies) {
    const source =
      reportCopy.source ??
      (await findUniqueFile(reportDirectory, reportCopy.sourceName));
    const destination = path.join(currentDirectory, reportCopy.destination);
    await mkdir(path.dirname(destination), { recursive: true });
    await copyFile(source, destination);
  }
  for (const fallback of generatedFallbacks) {
    const [testCase] = fallback.entry.cases;
    await writeFile(
      path.join(currentDirectory, path.basename(fallback.entry.previewPath)),
      fallbackSvg(fallback.project, testCase.description),
    );
    await writeFile(
      path.join(currentDirectory, path.basename(fallback.entry.reportPath)),
      fallbackHtml(fallback.project, testCase.description, workflowUrl),
    );
  }
  for (const entry of entries) {
    for (const testCase of entry.cases) {
      if (
        testCase.selection === 'workflow-failure' ||
        testCase.selection === 'first-failing-no-screenshot'
      ) {
        continue;
      }
      await copyFile(
        await findUniqueFile(
          reportDirectory,
          path.basename(testCase.previewPath),
        ),
        path.join(currentDirectory, path.basename(testCase.previewPath)),
      );
    }
  }
  await writeFile(path.join(currentDirectory, 'index.html'), buildRunIndex(current));

  const reports = [current, ...history];
  const manifest = {
    version: MANIFEST_VERSION,
    generatedAt,
    retention,
    reports,
  };
  await mkdir(path.join(siteDirectory, 'reports'), { recursive: true });
  await writeFile(
    path.join(siteDirectory, 'reports', 'manifest.json'),
    `${JSON.stringify(manifest, null, 2)}\n`,
  );
  await writeFile(path.join(siteDirectory, 'index.html'), buildIndex(reports));
  return manifest;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const manifest = await buildPagesReport(options);
  process.stdout.write(
    `Prepared ${manifest.reports.length} report(s); newest run is ${manifest.reports[0].runId}.\n`,
  );
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
}
