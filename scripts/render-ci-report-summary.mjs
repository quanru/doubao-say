#!/usr/bin/env node

import { appendFile, readFile } from 'node:fs/promises';
import process from 'node:process';

import { formatDuration } from './build-pages-report.mjs';

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
  if (!value) throw new Error(`Missing --${name}`);
  return value;
}

function normalizedBaseUrl(value) {
  const url = new URL(value);
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url;
}

function reportUrl(baseUrl, reportPath) {
  return new URL(reportPath, normalizedBaseUrl(baseUrl)).href;
}

function stepUrl(baseUrl, reportPath, stepId) {
  const url = new URL(reportPath, normalizedBaseUrl(baseUrl));
  if (!stepId) return url.href;
  url.hash = new URLSearchParams({ 'runner-step': stepId }).toString();
  return url.href;
}

function inlineCell(value) {
  return String(value)
    .replaceAll('\\', '\\\\')
    .replaceAll('|', '\\|')
    .replaceAll('[', '\\[')
    .replaceAll(']', '\\]')
    .replaceAll('\n', ' ');
}

function entryCounts(entry) {
  const parts = [];
  if (entry.scenarios.total > 0) {
    parts.push(
      `${entry.scenarios.passed}/${entry.scenarios.total} cases`,
    );
  }
  if (entry.assertions.total > 0) {
    parts.push(
      `${entry.assertions.passed}/${entry.assertions.total} assertions`,
    );
  }
  return `**${entry.label}: ${parts.join(' · ') || 'report captured'}.**`;
}

function caseTarget(pagesUrl, entry, testCase) {
  return stepUrl(
    pagesUrl,
    testCase.reportPath ?? entry.reportPath,
    testCase.stepId,
  );
}

function failureReason(testCase) {
  if (testCase.selection === 'workflow-failure') {
    return inlineCell(
      `CI failure before node capture — ${testCase.description ?? ''}`,
    );
  }
  const label = {
    ai: 'AI: ',
    error: 'Error: ',
    result: 'Result: ',
  }[testCase.descriptionKind];
  return inlineCell(`${label ?? ''}${testCase.description ?? ''}`);
}

// GFM has no layout grid, so a 3-column table of linked thumbnails acts as
// one. Each cell is the screenshot with the case name as caption below it.
function screenshotGrid(pagesUrl, entries, cases) {
  const cells = cases
    .filter(({ testCase }) => testCase.previewPath)
    .map(({ entry, testCase }) => {
    const target = caseTarget(pagesUrl, entry, testCase);
    const image = reportUrl(pagesUrl, testCase.previewPath);
    const name = inlineCell(testCase.name);
    return `[![${name}](${image})](${target})<br>[${name}](${target})`;
    });
  const rows = [];
  for (let index = 0; index < cells.length; index += 3) {
    const row = cells.slice(index, index + 3);
    while (row.length < 3) row.push('');
    rows.push(`| ${row.join(' | ')} |`);
  }
  if (rows.length === 0) return '';
  return ['| | | |', '|:--|:--|:--|', ...rows].join('\n');
}

export function renderReportSummary({
  manifest,
  pagesUrl,
  producerResult,
  runId,
  summaryTitle,
}) {
  const report = manifest.reports.find((item) => item.runId === runId);
  if (!report) throw new Error(`Run ${runId} is absent from the report manifest`);
  if (!Array.isArray(report.entries) || report.entries.length === 0) {
    throw new Error(`Run ${runId} does not contain structured report entries`);
  }

  const allPassed =
    producerResult === 'success' &&
    report.entries.every(
      (entry) =>
        entry.scenarios.total > 0 &&
        entry.scenarios.passed === entry.scenarios.total &&
        entry.assertions.passed === entry.assertions.total,
    );
  const title = `${summaryTitle} × Midscene · ${
    allPassed ? 'passed' : 'failure captured'
  }`;

  const groupedCases = report.entries.flatMap((entry) => {
    if (!Array.isArray(entry.cases) || entry.cases.length === 0) {
      throw new Error(`${entry.label} does not contain case evidence`);
    }
    return entry.cases.map((testCase) => ({ entry, testCase }));
  });
  groupedCases.forEach(({ testCase }) => {
    if (!testCase.description || !testCase.descriptionKind) {
      throw new Error(`${testCase.name} does not contain node text evidence`);
    }
  });

  const passedCases = groupedCases.filter(
    ({ testCase }) => testCase.status === 'success',
  );
  const failedCases = groupedCases.filter(
    ({ testCase }) => testCase.status !== 'success',
  );
  const failedScreenshots = failedCases.filter(
    ({ testCase }) => testCase.previewPath,
  );
  const screenshotCases = groupedCases.filter(
    ({ testCase }) => testCase.previewPath,
  );
  const totalCases = groupedCases.length;
  const passedCount = passedCases.length;
  const passRate =
    totalCases === 0 ? 0 : Math.round((passedCount / totalCases) * 100);

  const historyUrl = normalizedBaseUrl(pagesUrl).href;
  const links = [
    ...report.entries.flatMap((entry) => {
      const reports = entry.reports ?? [entry];
      return reports.map((nativeReport, index) => {
        const suffix = reports.length > 1 ? ` ${index + 1}` : '';
        return `[Open ${entry.label}${suffix}](${reportUrl(pagesUrl, nativeReport.reportPath)})`;
      });
    }),
    `[Report history](${historyUrl})`,
  ].join(' · ');

  const sections = [
    `## ${title}`,
    '',
    `**${passedCount}/${totalCases} cases · ${passRate}% passed**`,
    '',
    report.entries.map(entryCounts).join('\n\n'),
    '',
    links,
    '',
  ];

  if (failedCases.length === 0) {
    sections.push(`**All ${totalCases} cases passed.**`, '');
  } else {
    sections.push(
      `### Failures (${failedCases.length})`,
      '',
      '| Case | Duration | Reason |',
      '|:--|:--|:--|',
      ...failedCases.map(({ entry, testCase }) => {
        const target = caseTarget(pagesUrl, entry, testCase);
        const duration = formatDuration(testCase.durationMs) || '—';
        return `| ❌ [${inlineCell(testCase.name)}](${target}) | ${duration} | ${failureReason(testCase)} |`;
      }),
      '',
      `### Failed screenshots (${failedScreenshots.length})`,
      '',
      screenshotGrid(pagesUrl, report.entries, failedScreenshots) ||
        '_No failed-case screenshots were produced._',
      '',
    );
  }

  sections.push(
    `<details>`,
    `<summary>All screenshots (${screenshotCases.length})</summary>`,
    '',
    screenshotGrid(pagesUrl, report.entries, screenshotCases),
    '',
    `</details>`,
    '',
    `<details>`,
    `<summary>Passed cases (${passedCount})</summary>`,
    '',
    ...report.entries.flatMap((entry) => {
      const passed = (entry.cases ?? []).filter(
        (testCase) => testCase.status === 'success',
      );
      if (passed.length === 0) return [];
      return [
        `**${entry.label}**`,
        '',
        ...passed.map((testCase) => {
          const target = caseTarget(pagesUrl, entry, testCase);
          const duration = formatDuration(testCase.durationMs);
          return `- ✅ [${inlineCell(testCase.name)}](${target})${
            duration ? ` — ${duration}` : ''
          }`;
        }),
        '',
      ];
    }),
    `</details>`,
    '',
    'Each image is the original page screenshot used by that node. Cases remain linked to their native report when Midscene stops before producing a node screenshot. A CI failure card is shown only when a shard stops before Midscene can capture a report. Click a case name or image to open its evidence.',
    '',
  );

  return sections.join('\n');
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const manifest = JSON.parse(
    await readFile(required(options, 'manifest'), 'utf8'),
  );
  const summary = renderReportSummary({
    manifest,
    pagesUrl: required(options, 'pages-url'),
    producerResult: required(options, 'producer-result'),
    runId: required(options, 'run-id'),
    summaryTitle: required(options, 'summary-title'),
  });
  await appendFile(required(options, 'output'), summary);
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
}
