import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { buildPagesReport } from '../../scripts/build-pages-report.mjs';
import { findShellReport } from '../../scripts/omarchy-shell-evidence.mjs';
import { renderReportSummary } from '../../scripts/render-ci-report-summary.mjs';
import { verifyPublishedReport } from '../../scripts/verify-pages-report.mjs';

function runnerScript({
  assertionCount = 0,
  assertionAttempts,
  project,
  status = 'success',
  startedAt,
}) {
  const attempts =
    assertionAttempts ??
    (assertionCount
      ? [Array.from({ length: assertionCount }, () => 'success')]
      : []);
  return `<script type="midscene_test_run_dump">${JSON.stringify({
    startedAt,
    status,
    summary: {
      total: 1,
      passed: status === 'success' ? 1 : 0,
      failed: status === 'success' ? 0 : 1,
    },
    projects: [
      {
        name: project,
        documents: attempts.length
          ? [
              {
                cases: [
                  {
                    attempts: attempts.map((statuses, attemptIndex) => ({
                      steps: statuses.map((stepStatus, stepIndex) => ({
                        id: `assert-${attemptIndex}-${stepIndex}`,
                        node: 'aiAssert',
                        status: stepStatus,
                      })),
                    })),
                  },
                ],
              },
            ]
          : [],
      },
    ],
  })}</script>`;
}

const fixtureHtml = `<!doctype html><html><body>report
<script type="midscene_web_dump">{"usage":{"_midscene_call_id":"call-1","time_cost":2500,"total_tokens":120}}</script>
<script type="midscene_web_dump">{"message":"raw
control character","usage":{"_midscene_call_id":"call-2","time_cost":3500,"total_tokens":180}}</script>
${runnerScript({ project: 'ubuntu', startedAt: '2026-09-15T12:00:00Z' })}
</body></html>`;

const shellPrompts = [
  'The Omarchy system menu is open and Shutdown is readable.',
  'Exactly one row in the open system menu is highlighted.',
  'The Omarchy bar is visible on the left.',
];
const shellFixtureHtml = `<!doctype html><html><body>${shellPrompts
  .map(
    (prompt, index) => `
<script type="midscene_web_dump">${JSON.stringify({
      executions: [
        {
          tasks: [
            {
              status: 'finished',
              subType: 'Assert',
              param: { dataDemand: prompt },
              output: true,
              uiContext: { screenshot: { id: `image-${index}` } },
            },
          ],
        },
      ],
    })}</script>
<script type="midscene-image" data-id="image-${index}">data:image/jpeg;base64,/9j/2Q==</script>`,
  )
  .join('')}${runnerScript({ assertionCount: 3, project: 'omarchy-shell', startedAt: '2026-09-15T12:05:00Z' })}</body></html>`;

async function fixtureDirectory(root) {
  const reportDirectory = path.join(root, 'artifact', 'report');
  await mkdir(reportDirectory, { recursive: true });
  await writeFile(path.join(reportDirectory, 'test-run-ubuntu.html'), fixtureHtml);
  await writeFile(path.join(reportDirectory, 'agent-detail.html'), '<html>intermediate Agent report</html>');
  await writeFile(path.join(path.dirname(reportDirectory), 'report-preview.png'), 'preview');
  return path.dirname(reportDirectory);
}

async function startServer(handler) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  return {
    url: `http://127.0.0.1:${address.port}/`,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

function options(reportDirectory, siteDirectory, pagesUrl, runId = '200') {
  return {
    'report-dir': reportDirectory,
    'site-dir': siteDirectory,
    'run-id': runId,
    'workflow-url': `https://github.com/quanru/doubao-say/actions/runs/${runId}`,
    'generated-at': '2026-09-15T12:00:00Z',
    retention: '10',
    'pages-url': pagesUrl,
    label: 'Ubuntu 22.04',
    'primary-project': 'ubuntu',
  };
}

test('simulates a first deployment when Pages returns 404', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-first-'));
  const reportDirectory = await fixtureDirectory(root);
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) => {
    response.writeHead(404).end();
  });
  context.after(server.close);

  const manifest = await buildPagesReport({
    ...options(reportDirectory, siteDirectory, server.url),
    'auxiliary-project': 'ubuntu-polishing',
    'auxiliary-report-label': 'Polishing overlay report',
  });

  assert.equal(manifest.reports.length, 1);
  assert.equal(manifest.reports[0].runId, '200');
  assert.equal(manifest.reports[0].reportPath, 'reports/200/index.html');
  assert.equal(manifest.reports[0].successRate, 100);
  assert.equal(manifest.reports[0].averageDurationMs, 3000);
  assert.equal(manifest.reports[0].modelCallCount, 2);
  assert.equal(manifest.reports[0].tokenUsage, 300);
  const indexHtml = await readFile(
    path.join(siteDirectory, 'index.html'),
    'utf8',
  );
  assert.match(indexHtml, /Run ID/);
  assert.match(indexHtml, /Distribution/);
  assert.match(indexHtml, /Ubuntu 22\.04/);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'index.html'),
      'utf8',
    ),
    fixtureHtml,
  );
  assert.deepEqual(manifest.reports[0].files, [
    'reports/200/index.html',
    'reports/200/report-preview.png',
  ]);
  assert.equal(manifest.reports[0].entries.length, 1);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'report-preview.png'),
      'utf8',
    ),
    'preview',
  );
});

test('publishes the Doubao Say report as the primary CI entrance', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-omarchy-'));
  const reportDirectory = await fixtureDirectory(root);
  await writeFile(
    path.join(reportDirectory, 'report', 'test-run-shell.html'),
    shellFixtureHtml,
  );
  await writeFile(path.join(reportDirectory, 'report-preview.png'), 'preview');
  await writeFile(
    path.join(reportDirectory, 'auxiliary-report-preview.png'),
    'auxiliary preview',
  );
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport({
    ...options(reportDirectory, siteDirectory, server.url),
    'auxiliary-project': 'omarchy-shell',
    'auxiliary-report-label': 'Omarchy visual checks',
  });

  assert.equal(manifest.reports[0].testCount, 2);
  assert.equal(manifest.reports[0].successRate, 100);
  assert.deepEqual(manifest.reports[0].entries, [
    {
      role: 'primary',
      project: 'ubuntu',
      label: 'Doubao Say',
      status: 'success',
      previewStep: 'last',
      reportPath: 'reports/200/index.html',
      previewPath: 'reports/200/report-preview.png',
      scenarios: { passed: 1, total: 1 },
      assertions: { passed: 0, total: 0 },
    },
    {
      role: 'auxiliary',
      project: 'omarchy-shell',
      label: 'Omarchy visual checks',
      status: 'success',
      previewStep: 'last',
      reportPath: 'reports/200/auxiliary-report.html',
      previewPath: 'reports/200/auxiliary-report-preview.png',
      scenarios: { passed: 1, total: 1 },
      assertions: { passed: 3, total: 3 },
    },
  ]);
  assert.deepEqual(manifest.reports[0].files, [
    'reports/200/index.html',
    'reports/200/auxiliary-report.html',
    'reports/200/report-preview.png',
    'reports/200/auxiliary-report-preview.png',
  ]);
  const publishedReport = await readFile(
    path.join(siteDirectory, 'reports', '200', 'index.html'),
    'utf8',
  );
  assert.equal(publishedReport, fixtureHtml);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'auxiliary-report.html'),
      'utf8',
    ),
    shellFixtureHtml,
  );
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'report-preview.png'),
      'utf8',
    ),
    'preview',
  );
  assert.equal(
    await readFile(
      path.join(
        siteDirectory,
        'reports',
        '200',
        'auxiliary-report-preview.png',
      ),
      'utf8',
    ),
    'auxiliary preview',
  );
});

test('reports visual assertions from the final retry attempt only', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-retry-'));
  const reportDirectory = path.join(root, 'artifact', 'report');
  await mkdir(reportDirectory, { recursive: true });
  const retriedReport = `<!doctype html><html><body>${runnerScript({
    assertionAttempts: [['failed'], ['success', 'success']],
    project: 'ubuntu',
    startedAt: '2026-09-15T12:00:00Z',
  })}</body></html>`;
  await writeFile(
    path.join(reportDirectory, 'test-run-retried.html'),
    retriedReport,
  );
  await writeFile(
    path.join(path.dirname(reportDirectory), 'report-preview.png'),
    'preview',
  );
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport(
    options(path.dirname(reportDirectory), siteDirectory, server.url),
  );

  assert.deepEqual(manifest.reports[0].entries[0].assertions, {
    passed: 2,
    total: 2,
  });
});

test('publishes a failed shell report with its result in history', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-failed-'));
  const reportDirectory = await fixtureDirectory(root);
  await writeFile(
    path.join(reportDirectory, 'report', 'test-run-shell.html'),
    shellFixtureHtml
      .replace('"output":true', '"output":false')
      .replace(
        '"status":"success","summary":{"total":1,"passed":1,"failed":0}',
        '"status":"failed","summary":{"total":1,"passed":0,"failed":1}',
      ),
  );
  await writeFile(path.join(reportDirectory, 'report-preview.png'), 'failed');
  await writeFile(
    path.join(reportDirectory, 'auxiliary-report-preview.png'),
    'auxiliary failed',
  );
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport(
    {
      ...options(reportDirectory, siteDirectory, server.url),
      'auxiliary-project': 'omarchy-shell',
      'auxiliary-report-label': 'Omarchy visual checks',
    },
  );

  assert.equal(manifest.reports[0].successRate, 50);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'report-preview.png'),
      'utf8',
    ),
    'failed',
  );
});

test('keeps only the latest failed retry for an Omarchy project', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-retries-'));
  const reportDirectory = path.join(root, 'artifact');
  const reportPath = path.join(reportDirectory, 'report');
  await mkdir(reportPath, { recursive: true });
  const firstFailure = `<!doctype html><html><body>first failure${runnerScript({ project: 'omarchy-onboarding', status: 'failed', startedAt: '2026-09-15T13:00:00Z' })}</body></html>`;
  const finalFailure = `<!doctype html><html><body>final failure${runnerScript({ project: 'omarchy-onboarding', status: 'failed', startedAt: '2026-09-15T14:00:00Z' })}</body></html>`;
  await writeFile(path.join(reportPath, 'test-run-retry-1.html'), firstFailure);
  await writeFile(path.join(reportPath, 'test-run-retry-2.html'), finalFailure);
  await writeFile(path.join(reportDirectory, 'report-preview.png'), 'failed');
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport({
    ...options(reportDirectory, siteDirectory, server.url),
    label: 'Omarchy 4.0.3',
    'primary-project': 'omarchy-onboarding',
  });

  assert.equal(manifest.reports[0].successRate, 0);
  assert.equal(manifest.reports[0].testCount, 1);
  assert.deepEqual(manifest.reports[0].files, [
    'reports/200/index.html',
    'reports/200/report-preview.png',
  ]);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'index.html'),
      'utf8',
    ),
    finalFailure,
  );
});

test('restores retained history before adding the new run', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-history-'));
  const reportDirectory = await fixtureDirectory(root);
  const siteDirectory = path.join(root, 'site');
  const oldReport = '<!doctype html><html><body>old report</body></html>';
  const oldEntry = {
    runId: '100',
    generatedAt: '2026-09-14T12:00:00.000Z',
    label: 'Omarchy 4.0.3',
    successRate: 100,
    testCount: 1,
    averageDurationMs: 4000,
    modelCallCount: 1,
    tokenUsage: null,
    workflowUrl: 'https://github.com/quanru/doubao-say/actions/runs/100',
    reportPath: 'reports/100/index.html',
  };
  const server = await startServer((request, response) => {
    if (request.url === '/reports/manifest.json') {
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ version: 1, reports: [oldEntry] }));
    } else if (request.url === '/reports/100/index.html') {
      response.setHeader('content-type', 'text/html; charset=utf-8');
      response.end(oldReport);
    } else {
      response.writeHead(404).end();
    }
  });
  context.after(server.close);

  const manifest = await buildPagesReport(
    options(reportDirectory, siteDirectory, server.url),
  );

  assert.deepEqual(
    manifest.reports.map((report) => report.runId),
    ['200', '100'],
  );
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '100', 'index.html'),
      'utf8',
    ),
    oldReport,
  );
  const writtenManifest = JSON.parse(
    await readFile(
      path.join(siteDirectory, 'reports', 'manifest.json'),
      'utf8',
    ),
  );
  assert.equal(writtenManifest.version, 2);
  assert.equal(writtenManifest.reports[0].reportPath, 'reports/200/index.html');
  assert.equal(
    writtenManifest.reports[0].workflowUrl,
    'https://github.com/quanru/doubao-say/actions/runs/200',
  );
});

test('stops when a manifest exists but an old report cannot be restored', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-failure-'));
  const reportDirectory = await fixtureDirectory(root);
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((request, response) => {
    if (request.url === '/reports/manifest.json') {
      response.setHeader('content-type', 'application/json');
      response.end(
        JSON.stringify({
          version: 1,
          reports: [
            {
              runId: '100',
              workflowUrl:
                'https://github.com/quanru/doubao-say/actions/runs/100',
              reportPath: 'reports/100/index.html',
            },
          ],
        }),
      );
    } else {
      response.writeHead(503).end();
    }
  });
  context.after(server.close);

  await assert.rejects(
    buildPagesReport(options(reportDirectory, siteDirectory, server.url)),
    /Cannot restore report for run 100: HTTP 503/,
  );
});

test('rejects retention outside the supported range', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-retention-'));
  const reportDirectory = await fixtureDirectory(root);
  const server = await startServer((_request, response) => {
    response.writeHead(404).end();
  });
  context.after(server.close);
  const invalid = options(reportDirectory, path.join(root, 'site'), server.url);
  invalid.retention = '51';

  await assert.rejects(buildPagesReport(invalid), /integer from 1 to 50/);
});

test('rejects an undeclared report project', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-project-'));
  const reportDirectory = await fixtureDirectory(root);
  await writeFile(
    path.join(reportDirectory, 'report', 'test-run-shell.html'),
    shellFixtureHtml,
  );
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  await assert.rejects(
    buildPagesReport(
      options(reportDirectory, path.join(root, 'site'), server.url),
    ),
    /Unexpected Midscene Test project\(s\): omarchy-shell/,
  );
});

test('renders one full-width section per structured report entry', () => {
  const manifest = {
    reports: [
      {
        runId: '200',
        entries: [
          {
            role: 'primary',
            project: 'ubuntu',
            label: 'Doubao Say',
            status: 'success',
            previewStep: 'last',
            reportPath: 'reports/200/index.html',
            previewPath: 'reports/200/report-preview.png',
            scenarios: { passed: 6, total: 6 },
            assertions: { passed: 5, total: 5 },
          },
          {
            role: 'auxiliary',
            project: 'ubuntu-polishing',
            label: 'Polishing overlay report',
            status: 'success',
            previewStep: 'last',
            reportPath: 'reports/200/auxiliary-report.html',
            previewPath: 'reports/200/auxiliary-report-preview.png',
            scenarios: { passed: 1, total: 1 },
            assertions: { passed: 8, total: 8 },
          },
        ],
      },
    ],
  };
  const summary = renderReportSummary({
    manifest,
    pagesUrl: 'https://example.test/doubao-say/',
    producerResult: 'success',
    runId: '200',
    summaryTitle: 'Ubuntu',
  });

  assert.match(summary, /Ubuntu × Midscene · passed/);
  assert.match(summary, /Doubao Say: 6\/6 scenarios passed/);
  assert.match(summary, /Polishing overlay report: 1\/1 scenarios passed/);
  assert.doesNotMatch(summary, /\|:--\|/);
  assert.doesNotMatch(summary, /report report/);
  assert.match(summary, /Click the result previews/);
});

test('renders singular failure copy for one available report', () => {
  const manifest = {
    reports: [
      {
        runId: '200',
        entries: [
          {
            role: 'primary',
            project: 'ubuntu',
            label: 'Doubao Say',
            status: 'failed',
            previewStep: 'last-error',
            reportPath: 'reports/200/index.html',
            previewPath: 'reports/200/report-preview.png',
            scenarios: { passed: 0, total: 1 },
            assertions: { passed: 1, total: 2 },
          },
        ],
      },
    ],
  };
  const summary = renderReportSummary({
    manifest,
    pagesUrl: 'https://example.test/doubao-say',
    producerResult: 'failure',
    runId: '200',
    summaryTitle: 'Ubuntu',
  });

  assert.match(summary, /Ubuntu × Midscene · failure captured/);
  assert.match(summary, /Most recent error from Doubao Say/);
  assert.match(summary, /Click the result preview to inspect/);
  assert.doesNotMatch(summary, /Click the result previews/);
});

test('finds Omarchy evidence by project instead of assertion wording', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'shell-project-'));
  const reportDirectory = path.join(root, 'report');
  await mkdir(reportDirectory, { recursive: true });
  await writeFile(
    path.join(reportDirectory, 'test-run-shell.html'),
    shellFixtureHtml
      .replace(shellPrompts[0], 'Renamed menu assertion.')
      .replace(shellPrompts[1], 'Renamed focus assertion.')
      .replace(shellPrompts[2], 'Renamed bar assertion.'),
  );

  const report = await findShellReport(root);
  assert.deepEqual(
    report.checks.map(({ key, passed }) => ({ key, passed })),
    [
      { key: 'shutdown', passed: true },
      { key: 'focus', passed: true },
      { key: 'bar', passed: true },
    ],
  );
});

test('verifies every file and its expected content type', async () => {
  const requested = [];
  const manifest = {
    reports: [
      {
        runId: '200',
        files: [
          'reports/200/index.html',
          'reports/200/auxiliary-report.html',
          'reports/200/report-preview.png',
          'reports/200/auxiliary-report-preview.png',
        ],
      },
    ],
  };
  await verifyPublishedReport({
    manifest,
    pagesUrl: 'https://example.test/doubao-say/',
    runId: '200',
    fetchImpl: async (url) => {
      requested.push(url.href);
      return new Response(null, {
        status: 200,
        headers: {
          'content-type': url.pathname.endsWith('.png')
            ? 'image/png'
            : 'text/html; charset=utf-8',
        },
      });
    },
  });

  assert.deepEqual(requested, [
    'https://example.test/doubao-say/',
    'https://example.test/doubao-say/reports/200/index.html',
    'https://example.test/doubao-say/reports/200/auxiliary-report.html',
    'https://example.test/doubao-say/reports/200/report-preview.png',
    'https://example.test/doubao-say/reports/200/auxiliary-report-preview.png',
  ]);
});
