import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { buildPagesReport } from '../../scripts/build-pages-report.mjs';
import {
  findShellReport,
  testRunDump,
} from '../../scripts/omarchy-shell-evidence.mjs';
import { reportCases } from '../../scripts/report-cases.mjs';
import { renderReportSummary } from '../../scripts/render-ci-report-summary.mjs';
import { verifyPublishedReport } from '../../scripts/verify-pages-report.mjs';

test('publishes the Markdown evidence table for same-repository pull requests', async () => {
  for (const workflow of [
    'midscene-ubuntu-22.04.yml',
    'midscene-omarchy-4.0.3.yml',
  ]) {
    const source = await readFile(
      new URL(`../../.github/workflows/${workflow}`, import.meta.url),
      'utf8',
    );
    const pagesJob = source.slice(source.indexOf('  pages-report:'));
    assert.match(
      pagesJob,
      /github\.event\.pull_request\.head\.repo\.full_name == github\.repository/,
      `${workflow} must publish its report and Summary table for trusted PRs`,
    );
    assert.doesNotMatch(
      pagesJob,
      /github\.ref_name == vars\.PAGES_REPORT_BRANCH/,
      `${workflow} must not suppress the PR Summary table behind a branch check`,
    );
  }
});

test('records every shard and renders the Summary before Pages deployment', async () => {
  for (const workflow of [
    'midscene-ubuntu-22.04.yml',
    'midscene-omarchy-4.0.3.yml',
  ]) {
    const source = await readFile(
      new URL(`../../.github/workflows/${workflow}`, import.meta.url),
      'utf8',
    );
    assert.match(source, /Record shard result for report aggregation/);
    assert.match(
      source,
      /if: always\(\) && !cancelled\(\)/,
      `${workflow} must preserve failure evidence without extending manually cancelled runs`,
    );
    assert.match(
      source,
      /max-parallel: 5/,
      `${workflow} must start all four product shards and its auxiliary project together`,
    );
    assert.match(source, /if-no-files-found: error/);
    assert.match(source, /Create bundle even when every shard failed early/);
    assert.match(
      source,
      /Upload .*shard report[\s\S]*?overwrite: true/,
      `${workflow} must replace a rerun shard artifact instead of keeping duplicate names`,
    );
    assert.match(
      source,
      /Upload combined report bundle[\s\S]*?overwrite: true/,
      `${workflow} must replace the previous attempt's combined bundle`,
    );
  }

  const deploy = await readFile(
    new URL('../../.github/workflows/deploy-midscene-report.yml', import.meta.url),
    'utf8',
  );
  const summary = deploy.indexOf('Add complete evidence table');
  const deployment = deploy.indexOf('Deploy report history to GitHub Pages');
  const deployJob = deploy.indexOf('\n  deploy:');
  assert.ok(summary > 0 && summary < deployment);
  assert.match(
    deploy.slice(summary, deployment),
    /steps\.build-report\.outcome == 'success'/,
  );
  assert.ok(deployJob > summary);
  assert.doesNotMatch(deploy.slice(0, deployJob), /environment:/);
  assert.match(
    deploy,
    /name: \$\{\{ inputs\.artifact-name \}\}-pages-\$\{\{ github\.run_attempt \}\}/,
  );
  assert.match(
    deploy,
    /artifact_name: \$\{\{ inputs\.artifact-name \}\}-pages-\$\{\{ github\.run_attempt \}\}/,
  );
  assert.match(
    deploy,
    /name: \$\{\{ inputs\.artifact-name \}\}-manifest-\$\{\{ github\.run_attempt \}\}/,
  );
});

test('assigns every product case to exactly one balanced shard', async () => {
  const shardCounts = new Map();
  let caseCount = 0;
  for (const file of [
    'onboarding.yaml',
    'onboarding-regressions.yaml',
    'runtime.yaml',
  ]) {
    const source = await readFile(
      new URL(`../e2e/cases/${file}`, import.meta.url),
      'utf8',
    );
    const cases = source
      .split(/(?=^  - name:)/m)
      .filter((section) => section.startsWith('  - name:'));
    for (const testCase of cases) {
      const tags = [...testCase.matchAll(/^    tags: \[([^\]]+)\]$/gm)];
      assert.equal(tags.length, 1, testCase.split('\n')[0]);
      const shards = tags[0][1].split(',').map((tag) => tag.trim())
        .filter((tag) => /^shard-[1-4]$/.test(tag));
      assert.equal(shards.length, 1, testCase.split('\n')[0]);
      shardCounts.set(shards[0], (shardCounts.get(shards[0]) ?? 0) + 1);
      caseCount += 1;
    }
  }
  assert.equal(caseCount, 14);
  assert.deepEqual(Object.fromEntries(shardCounts), {
    'shard-1': 2,
    'shard-2': 3,
    'shard-3': 5,
    'shard-4': 4,
  });
});

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
      : [[status === 'success' ? 'success' : 'failed']]);
  const reportId = 'runner-report-1';
  const executions = attempts.flatMap((statuses, attemptIndex) =>
    statuses.map((stepStatus, stepIndex) => ({
      id: `execution-${attemptIndex}-${stepIndex}`,
      tasks: [
        {
          status: stepStatus === 'success' ? 'finished' : 'failed',
          type: 'Insight',
          subType: 'Assert',
          uiContext: {
            screenshot: {
              id: `screenshot-${attemptIndex}-${stepIndex}`,
              mimeType: 'image/jpeg',
              storage: 'inline',
            },
          },
          thought:
            stepStatus === 'success'
              ? `AI explanation ${attemptIndex}-${stepIndex}`
              : `AI failure explanation ${attemptIndex}-${stepIndex}`,
        },
      ],
    })),
  );
  const run = {
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
        documents: [
              {
                cases: [
                  {
                    caseId: `case-${project}`,
                    name: `${project} visual case`,
                    status,
                    attempts: attempts.map((statuses, attemptIndex) => ({
                      status: statuses.every((item) => item === 'success')
                        ? 'success'
                        : 'failed',
                      steps: statuses.map((stepStatus, stepIndex) => ({
                        id: `assert-${attemptIndex}-${stepIndex}`,
                        node: assertionCount || assertionAttempts ? 'aiAssert' : 'aiAct',
                        title: `Evidence ${attemptIndex}-${stepIndex}`,
                        status: stepStatus,
                        ...(stepStatus === 'failed'
                          ? {
                              error: {
                                message: `Fixture error ${attemptIndex}-${stepIndex}`,
                              },
                            }
                          : {}),
                        agentDetails: [{ reportId, executionId: `execution-${attemptIndex}-${stepIndex}` }],
                      })),
                    })),
                  },
                ],
              },
            ],
      },
    ],
  };
  return `<script type="midscene_web_dump" data-report-id="${reportId}">${JSON.stringify({ executions })}</script>
${attempts
  .flatMap((statuses, attemptIndex) =>
    statuses.map(
      (_stepStatus, stepIndex) =>
        `<script type="midscene-image" data-id="screenshot-${attemptIndex}-${stepIndex}">data:image/jpeg;base64,/9j/2Q==</script>`,
    ),
  )
  .join('\n')}
<script type="midscene_test_run_dump">${JSON.stringify(run)}</script>`;
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
  await writeFile(
    path.join(path.dirname(reportDirectory), 'case-preview-ubuntu-case-ubuntu.jpg'),
    'ubuntu case preview',
  );
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
  const runIndex = await readFile(
    path.join(siteDirectory, 'reports', '200', 'index.html'),
    'utf8',
  );
  assert.match(runIndex, /Node screenshot/);
  assert.match(runIndex, /AI response \/ error/);
  assert.match(runIndex, /ubuntu visual case/);
  assert.match(
    runIndex,
    /native-report\.html#runner-step=assert-0-0/,
  );
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'native-report.html'),
      'utf8',
    ),
    fixtureHtml,
  );
  assert.deepEqual(manifest.reports[0].files, [
    'reports/200/index.html',
    'reports/200/native-report.html',
    'reports/200/report-preview.png',
    'reports/200/case-preview-ubuntu-case-ubuntu.jpg',
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

test('combines independently executed shards into one report table', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-shards-'));
  const reportDirectory = path.join(root, 'bundle');
  for (const project of ['ubuntu-shard-1', 'ubuntu-shard-2']) {
    const shardDirectory = path.join(reportDirectory, project);
    const htmlDirectory = path.join(shardDirectory, 'report');
    await mkdir(htmlDirectory, { recursive: true });
    await writeFile(
      path.join(htmlDirectory, `test-run-${project}.html`),
      runnerScript({ project, startedAt: '2026-09-15T12:00:00Z' }),
    );
    await writeFile(
      path.join(shardDirectory, `report-preview-${project}.png`),
      `${project} preview`,
    );
    await writeFile(
      path.join(
        shardDirectory,
        `case-preview-${project}-case-${project}.jpg`,
      ),
      `${project} case preview`,
    );
  }
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport({
    ...options(reportDirectory, siteDirectory, server.url),
    'report-groups': JSON.stringify([
      {
        role: 'primary',
        label: 'Doubao Say',
        projects: ['ubuntu-shard-1', 'ubuntu-shard-2'],
      },
    ]),
  });

  const [entry] = manifest.reports[0].entries;
  assert.deepEqual(entry.projects, ['ubuntu-shard-1', 'ubuntu-shard-2']);
  assert.equal(entry.cases.length, 2);
  assert.equal(entry.scenarios.total, 2);
  assert.notEqual(entry.cases[0].reportPath, entry.cases[1].reportPath);
  const runIndex = await readFile(
    path.join(siteDirectory, 'reports', '200', 'index.html'),
    'utf8',
  );
  assert.match(
    runIndex,
    /native-report-ubuntu-shard-1\.html#runner-step=assert-0-0/,
  );
  assert.match(
    runIndex,
    /native-report-ubuntu-shard-2\.html#runner-step=assert-0-0/,
  );
  const summary = renderReportSummary({
    manifest,
    pagesUrl: 'https://example.test/doubao-say/',
    producerResult: 'success',
    runId: '200',
    summaryTitle: 'Ubuntu',
  });
  assert.match(
    summary,
    /native-report-ubuntu-shard-1\.html#runner-step=assert-0-0/,
  );
  assert.match(
    summary,
    /native-report-ubuntu-shard-2\.html#runner-step=assert-0-0/,
  );
});

test('keeps a complete Markdown table when a shard produces no native report', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-partial-shards-'));
  const reportDirectory = path.join(root, 'reports');
  const shardDirectory = path.join(reportDirectory, 'ubuntu-shard-1');
  await mkdir(path.join(shardDirectory, 'report'), { recursive: true });
  await writeFile(
    path.join(shardDirectory, 'report', 'test-run-ubuntu-shard-1.html'),
    runnerScript({
      project: 'ubuntu-shard-1',
      startedAt: '2026-09-15T12:00:00Z',
    }),
  );
  await writeFile(
    path.join(shardDirectory, 'report-preview-ubuntu-shard-1.png'),
    'preview',
  );
  await writeFile(
    path.join(
      shardDirectory,
      'case-preview-ubuntu-shard-1-case-ubuntu-shard-1.jpg',
    ),
    'case preview',
  );
  await writeFile(
    path.join(shardDirectory, 'ci-shard-status-ubuntu-shard-2.json'),
    JSON.stringify({
      project: 'ubuntu-shard-2',
      result: 'failure',
      stage: 'workflow setup before test execution',
    }),
  );
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport({
    ...options(reportDirectory, siteDirectory, server.url),
    'report-groups': JSON.stringify([
      {
        role: 'primary',
        label: 'Doubao Say',
        projects: ['ubuntu-shard-1', 'ubuntu-shard-2'],
      },
    ]),
  });
  const [entry] = manifest.reports[0].entries;
  assert.equal(entry.cases.length, 2);
  assert.equal(entry.cases[1].selection, 'workflow-failure');
  assert.match(entry.cases[1].description, /workflow setup/);
  await readFile(
    path.join(
      siteDirectory,
      'reports',
      '200',
      'shard-failure-ubuntu-shard-2.svg',
    ),
  );

  const summary = renderReportSummary({
    manifest,
    pagesUrl: 'https://example.test/doubao-say/',
    producerResult: 'failure',
    runId: '200',
    summaryTitle: 'Ubuntu',
  });
  assert.match(summary, /ubuntu-shard-1 visual case/);
  assert.match(summary, /ubuntu-shard-2 CI shard/);
  assert.match(summary, /CI failure before node capture/);
  assert.match(summary, /workflow setup before test execution/);
  assert.doesNotMatch(summary, /runner-step=.*infrastructure-ubuntu-shard-2/);
});

test('uses a failure row when node evidence extraction fails', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-capture-failed-'));
  const reportDirectory = await fixtureDirectory(root);
  await writeFile(
    path.join(reportDirectory, 'ci-shard-status-ubuntu.json'),
    JSON.stringify({
      project: 'ubuntu',
      result: 'failure',
      stage: 'report evidence capture',
      testOutcome: 'success',
      captureOutcome: 'failure',
    }),
  );
  const siteDirectory = path.join(root, 'site');
  const server = await startServer((_request, response) =>
    response.writeHead(404).end(),
  );
  context.after(server.close);

  const manifest = await buildPagesReport({
    ...options(reportDirectory, siteDirectory, server.url),
    'report-groups': JSON.stringify([
      { role: 'primary', label: 'Doubao Say', projects: ['ubuntu'] },
    ]),
  });
  const [testCase] = manifest.reports[0].entries[0].cases;
  assert.equal(testCase.selection, 'workflow-failure');
  assert.match(testCase.description, /report evidence capture/);
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
  await writeFile(
    path.join(reportDirectory, 'case-preview-omarchy-shell-case-omarchy-shell.jpg'),
    'shell case preview',
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
      reportPath: 'reports/200/native-report.html',
      previewPath: 'reports/200/report-preview.png',
      scenarios: { passed: 1, total: 1 },
      assertions: { passed: 0, total: 0 },
      cases: [
        {
          caseId: 'case-ubuntu',
          name: 'ubuntu visual case',
          status: 'success',
          stepId: 'assert-0-0',
          selection: 'last-screenshot',
          description: 'AI explanation 0-0',
          descriptionKind: 'ai',
          previewPath: 'reports/200/case-preview-ubuntu-case-ubuntu.jpg',
        },
      ],
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
      cases: [
        {
          caseId: 'case-omarchy-shell',
          name: 'omarchy-shell visual case',
          status: 'success',
          stepId: 'assert-0-2',
          selection: 'last-screenshot',
          description: 'AI explanation 0-2',
          descriptionKind: 'ai',
          previewPath:
            'reports/200/case-preview-omarchy-shell-case-omarchy-shell.jpg',
        },
      ],
    },
  ]);
  assert.deepEqual(manifest.reports[0].files, [
    'reports/200/index.html',
    'reports/200/native-report.html',
    'reports/200/auxiliary-report.html',
    'reports/200/report-preview.png',
    'reports/200/auxiliary-report-preview.png',
    'reports/200/case-preview-ubuntu-case-ubuntu.jpg',
    'reports/200/case-preview-omarchy-shell-case-omarchy-shell.jpg',
  ]);
  const publishedIndex = await readFile(
    path.join(siteDirectory, 'reports', '200', 'index.html'),
    'utf8',
  );
  assert.match(publishedIndex, /Doubao Say/);
  assert.match(publishedIndex, /Omarchy visual checks/);
  assert.match(publishedIndex, /AI response \/ error/);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'native-report.html'),
      'utf8',
    ),
    fixtureHtml,
  );
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
  await writeFile(
    path.join(
      path.dirname(reportDirectory),
      'case-preview-ubuntu-case-ubuntu.jpg',
    ),
    'retry preview',
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
  await writeFile(
    path.join(
      reportDirectory,
      'case-preview-omarchy-shell-case-omarchy-shell.jpg',
    ),
    'shell failure preview',
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
  await writeFile(
    path.join(
      reportDirectory,
      'case-preview-omarchy-onboarding-case-omarchy-onboarding.jpg',
    ),
    'failure preview',
  );
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
    'reports/200/native-report.html',
    'reports/200/report-preview.png',
    'reports/200/case-preview-omarchy-onboarding-case-omarchy-onboarding.jpg',
  ]);
  const failedRunIndex = await readFile(
    path.join(siteDirectory, 'reports', '200', 'index.html'),
    'utf8',
  );
  assert.match(failedRunIndex, /❌ Failed/);
  assert.match(failedRunIndex, /Error:/);
  assert.equal(
    await readFile(
      path.join(siteDirectory, 'reports', '200', 'native-report.html'),
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
  assert.equal(writtenManifest.version, 5);
  assert.equal(writtenManifest.reports[0].reportPath, 'reports/200/index.html');
  assert.equal(
    writtenManifest.reports[0].workflowUrl,
    'https://github.com/quanru/doubao-say/actions/runs/200',
  );
});

test('restores version 4 history created before node text evidence', async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'pages-v4-history-'));
  const reportDirectory = await fixtureDirectory(root);
  const siteDirectory = path.join(root, 'site');
  const files = [
    'reports/100/index.html',
    'reports/100/report-preview.png',
    'reports/100/case-preview-ubuntu-old-case.jpg',
  ];
  const oldEntry = {
    runId: '100',
    generatedAt: '2026-09-14T12:00:00.000Z',
    label: 'Ubuntu 22.04',
    successRate: 100,
    testCount: 1,
    modelCallCount: 1,
    averageDurationMs: 4000,
    tokenUsage: 100,
    workflowUrl: 'https://github.com/quanru/doubao-say/actions/runs/100',
    reportPath: files[0],
    files,
    entries: [{
      role: 'primary', project: 'ubuntu', label: 'Doubao Say',
      status: 'success', previewStep: 'last', reportPath: files[0],
      previewPath: files[1], scenarios: { passed: 1, total: 1 },
      assertions: { passed: 1, total: 1 },
      cases: [{
        caseId: 'old-case', name: 'Old visual case', status: 'success',
        stepId: 'old-step', selection: 'last-screenshot', previewPath: files[2],
      }],
    }],
  };
  const server = await startServer((request, response) => {
    if (request.url === '/reports/manifest.json') {
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ version: 4, reports: [oldEntry] }));
      return;
    }
    const file = files.find((candidate) => `/${candidate}` === request.url);
    if (!file) return response.writeHead(404).end();
    response.setHeader(
      'content-type',
      file.endsWith('.html') ? 'text/html; charset=utf-8' : 'image/png',
    );
    response.end(file);
  });
  context.after(server.close);

  const manifest = await buildPagesReport(
    options(reportDirectory, siteDirectory, server.url),
  );
  assert.deepEqual(manifest.reports.map((report) => report.runId), ['200', '100']);
  assert.equal(manifest.reports[1].entries[0].cases[0].description, undefined);
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
            cases: [
              {
                caseId: 'case-ubuntu',
                name: 'Launch and finish onboarding',
                status: 'success',
                stepId: 'case-ubuntu:steps:8',
                selection: 'last-screenshot',
                description: 'The setup completion state is visible.',
                descriptionKind: 'ai',
                previewPath:
                  'reports/200/case-preview-ubuntu-case-ubuntu.jpg',
              },
            ],
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
            cases: [
              {
                caseId: 'case-polishing',
                name: 'Polish selected text',
                status: 'success',
                stepId: 'case-polishing:steps:5',
                selection: 'last-screenshot',
                description: 'The polished text is visible.',
                descriptionKind: 'ai',
                previewPath:
                  'reports/200/case-preview-ubuntu-polishing-case-polishing.jpg',
              },
            ],
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
  assert.match(
    summary,
    /\| Result \| Case \| Node screenshot \| AI response \/ error \|/,
  );
  assert.match(summary, /✅ Passed/);
  assert.match(
    summary,
    /index\.html#runner-step=case-ubuntu%3Asteps%3A8/,
  );
  assert.match(summary, /Last screenshot: Launch and finish onboarding/);
  assert.match(summary, /\*\*AI:\*\* The setup completion state is visible\./);
  assert.doesNotMatch(summary, /report report/);
  assert.match(summary, /Each image is the original page screenshot/);
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
            cases: [
              {
                caseId: 'case-fail',
                name: 'Broken flow',
                status: 'failed',
                stepId: 'case-fail:steps:2',
          selection: 'first-failing-screenshot',
                description: 'Node "aiAssert" failed: expected state missing.',
                descriptionKind: 'error',
                previewPath:
                  'reports/200/case-preview-ubuntu-case-fail.jpg',
              },
            ],
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
  assert.match(summary, /❌ Failed/);
  assert.match(summary, /First failing screenshot: Broken flow/);
  assert.match(
    summary,
    /\*\*Error:\*\* Node "aiAssert" failed: expected state missing\./,
  );
  assert.match(
    summary,
    /index\.html#runner-step=case-fail%3Asteps%3A2/,
  );
  assert.match(summary, /Each image is the original page screenshot/);
});

test('selects the last screenshot for success and first failed screenshot for failure', () => {
  const run = {
    projects: [
      {
        name: 'ubuntu',
        documents: [
          {
            cases: [
              {
                caseId: 'passed-case',
                name: 'Passed case',
                status: 'success',
                attempts: [
                  {
                    status: 'success',
                    steps: [
                      { id: 'pass-1', status: 'success', agentDetails: [{}] },
                      { id: 'pass-2', status: 'success' },
                    ],
                  },
                ],
              },
              {
                caseId: 'failed-case',
                name: 'Failed case',
                status: 'failed',
                attempts: [
                  {
                    status: 'failed',
                    steps: [
                      { id: 'fail-1', status: 'failed', agentDetails: [{}] },
                      { id: 'fail-2', status: 'failed', agentDetails: [{}] },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  };

  assert.deepEqual(
    reportCases(run, 'ubuntu').map(({ caseId, stepId, selection }) => ({
      caseId,
      stepId,
      selection,
    })),
    [
      {
        caseId: 'passed-case',
        stepId: 'pass-1',
        selection: 'last-screenshot',
      },
      {
        caseId: 'failed-case',
        stepId: 'fail-1',
        selection: 'first-failing-screenshot',
      },
    ],
  );
});

test('pairs an original node screenshot with its AI text or error', () => {
  const successHtml = runnerScript({
    project: 'ubuntu',
    startedAt: '2026-09-15T12:00:00Z',
  });
  const success = reportCases(testRunDump(successHtml), 'ubuntu', {
    reportHtml: successHtml,
  })[0];
  assert.equal(success.descriptionKind, 'ai');
  assert.equal(success.description, 'AI explanation 0-0');
  assert.deepEqual(success.screenshot.bytes, Buffer.from('/9j/2Q==', 'base64'));

  const failureHtml = runnerScript({
    project: 'ubuntu',
    startedAt: '2026-09-15T12:00:00Z',
    status: 'failed',
  });
  const failure = reportCases(testRunDump(failureHtml), 'ubuntu', {
    reportHtml: failureHtml,
  })[0];
  assert.equal(failure.descriptionKind, 'error');
  assert.equal(failure.description, 'Fixture error 0-0');
  assert.deepEqual(failure.screenshot.bytes, Buffer.from('/9j/2Q==', 'base64'));
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
          'reports/200/case-preview-ubuntu-case-ubuntu.jpg',
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
            : url.pathname.endsWith('.jpg')
              ? 'image/jpeg'
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
    'https://example.test/doubao-say/reports/200/case-preview-ubuntu-case-ubuntu.jpg',
  ]);
});
