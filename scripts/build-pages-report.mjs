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

const MANIFEST_VERSION = 2;
const SUPPORTED_MANIFEST_VERSIONS = new Set([1, MANIFEST_VERSION]);

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

function buildReportEntry({
  label,
  previewPath,
  project,
  report,
  reportPath,
  role,
}) {
  const status = report.run?.status ?? 'unknown';
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
  };
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
              !/^reports\/\d+\/[a-z0-9.-]+$/.test(file) ||
              !file.startsWith(`reports/${report.runId}/`),
          ))) ||
      (report.entries !== undefined &&
        (!Array.isArray(report.entries) ||
          report.entries.some(
            (entry) =>
              !['primary', 'auxiliary'].includes(entry.role) ||
              typeof entry.project !== 'string' ||
              typeof entry.label !== 'string' ||
              typeof entry.status !== 'string' ||
              !['last', 'last-error'].includes(entry.previewStep) ||
              !report.files?.includes(entry.reportPath) ||
              !report.files?.includes(entry.previewPath) ||
              !Number.isInteger(entry.scenarios?.passed) ||
              !Number.isInteger(entry.scenarios?.total) ||
              !Number.isInteger(entry.assertions?.passed) ||
              !Number.isInteger(entry.assertions?.total),
          )))
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
  for (const file of report.files ?? [report.reportPath]) {
    const response = await fetch(new URL(file, baseUrl), {
      redirect: 'follow',
    });
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
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatDuration(durationMs) {
  if (durationMs === null) return 'Unavailable';
  return `${(durationMs / 1000).toFixed(2)} s`;
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
            <td>${escapeHtml(formatDuration(report.averageDurationMs))}</td>
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
  const primaryProject = required(options, 'primary-project');
  const primaryReportLabel = options['primary-report-label'] || 'Doubao Say';
  const auxiliaryProject = options['auxiliary-project'];
  const auxiliaryReportLabel = options['auxiliary-report-label'];
  if (Boolean(auxiliaryProject) !== Boolean(auxiliaryReportLabel)) {
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

  const reportCandidates = await Promise.all(
    (await findHtmlFiles(reportDirectory)).map(async (file) => ({
      file,
      html: await readFile(file, 'utf8'),
    })),
  );
  const latestByProject = new Map();
  for (const report of reportCandidates) {
    report.run = testRunDump(report.html);
    report.startedAt = Date.parse(report.run?.startedAt ?? '') || 0;
    const projectKey =
      report.run?.projects?.map((project) => project.name).join(',') ||
      path.basename(report.file);
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
  const primaryReport = reportForProject(primaryProject);
  if (!primaryReport) {
    throw new Error(`No Midscene Test report found for project ${primaryProject}`);
  }
  const auxiliaryReport = auxiliaryProject
    ? reportForProject(auxiliaryProject)
    : null;
  const selectedReports = [primaryReport, auxiliaryReport].filter(Boolean);
  const selectedFiles = new Set(selectedReports.map((report) => report.file));
  const unexpectedProjects = htmlReports
    .filter((report) => !selectedFiles.has(report.file))
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
  const reportPrefix = `reports/${runId}`;
  const files = auxiliaryReport
    ? [
        'index.html',
        'auxiliary-report.html',
        'report-preview.png',
        'auxiliary-report-preview.png',
      ].map((name) => `${reportPrefix}/${name}`)
    : [
        `${reportPrefix}/index.html`,
        `${reportPrefix}/report-preview.png`,
      ];
  const entries = [
    buildReportEntry({
      role: 'primary',
      project: primaryProject,
      label: primaryReportLabel,
      report: primaryReport,
      reportPath: `${reportPrefix}/index.html`,
      previewPath: `${reportPrefix}/report-preview.png`,
    }),
    ...(auxiliaryReport
      ? [
          buildReportEntry({
            role: 'auxiliary',
            project: auxiliaryProject,
            label: auxiliaryReportLabel,
            report: auxiliaryReport,
            reportPath: `${reportPrefix}/auxiliary-report.html`,
            previewPath: `${reportPrefix}/auxiliary-report-preview.png`,
          }),
        ]
      : []),
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
  if (auxiliaryReport) {
    await copyFile(primaryReport.file, path.join(currentDirectory, 'index.html'));
    await copyFile(auxiliaryReport.file, path.join(currentDirectory, 'auxiliary-report.html'));
    await copyFile(path.join(reportDirectory, 'report-preview.png'), path.join(currentDirectory, 'report-preview.png'));
    await copyFile(
      path.join(reportDirectory, 'auxiliary-report-preview.png'),
      path.join(currentDirectory, 'auxiliary-report-preview.png'),
    );
  } else {
    await copyFile(primaryReport.file, path.join(currentDirectory, 'index.html'));
    await copyFile(
      path.join(reportDirectory, 'report-preview.png'),
      path.join(currentDirectory, 'report-preview.png'),
    );
  }

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
