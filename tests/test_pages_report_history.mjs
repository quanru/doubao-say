import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { buildPagesReport } from '../scripts/build-pages-report.mjs';

const fixtureHtml = `<!doctype html><html><body>report
<script type="midscene_web_dump">{"usage":{"_midscene_call_id":"call-1","time_cost":2500,"total_tokens":120}}</script>
<script type="midscene_web_dump">{"message":"raw
control character","usage":{"_midscene_call_id":"call-2","time_cost":3500,"total_tokens":180}}</script>
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
  .join('')}</body></html>`;

async function fixtureDirectory(root) {
  const reportDirectory = path.join(root, 'artifact', 'report');
  await mkdir(reportDirectory, { recursive: true });
  await writeFile(path.join(reportDirectory, 'test-run-ubuntu.html'), fixtureHtml);
  await writeFile(path.join(reportDirectory, 'agent-detail.html'), '<html>intermediate Agent report</html>');
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

  const manifest = await buildPagesReport(
    options(reportDirectory, siteDirectory, server.url),
  );

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
});

test('publishes the shell test-run report directly with a CI entrance image', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-omarchy-'));
  const reportDirectory = await fixtureDirectory(root);
  await writeFile(
    path.join(reportDirectory, 'report', 'test-run-shell.html'),
    shellFixtureHtml,
  );
  await writeFile(path.join(reportDirectory, 'report-preview.png'), 'preview');
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport(
    options(reportDirectory, siteDirectory, server.url),
  );

  assert.equal(manifest.reports[0].testCount, 2);
  assert.equal(manifest.reports[0].successRate, 100);
  assert.equal(manifest.reports[0].files.length, 3);
  const publishedReport = await readFile(
    path.join(siteDirectory, 'reports', '200', 'index.html'),
    'utf8',
  );
  assert.equal(publishedReport, shellFixtureHtml);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'onboarding-report.html'),
      'utf8',
    ),
    fixtureHtml,
  );
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'report-preview.png'),
      'utf8',
    ),
    'preview',
  );
});

test('publishes a failed shell report with its result in history', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-failed-'));
  const reportDirectory = await fixtureDirectory(root);
  await writeFile(
    path.join(reportDirectory, 'report', 'test-run-shell.html'),
    shellFixtureHtml.replace('"output":true', '"output":false'),
  );
  await writeFile(path.join(reportDirectory, 'report-preview.png'), 'failed');
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport(
    options(reportDirectory, siteDirectory, server.url),
  );

  assert.equal(manifest.reports[0].successRate, 67);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'report-preview.png'),
      'utf8',
    ),
    'failed',
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
