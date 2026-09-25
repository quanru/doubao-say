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
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll(/[\r\n]+/g, ' ');
}

function htmlAttribute(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
    .replaceAll('|', '&#124;')
    .replaceAll(/[\r\n]+/g, ' ');
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
    return `CI failure before node capture — ${testCase.description ?? ''}`;
  }
  const label = {
    ai: 'AI: ',
    error: 'Error: ',
    result: 'Result: ',
  }[testCase.descriptionKind];
  return `${label ?? ''}${testCase.description ?? ''}`;
}

function caseProject(entry, testCase) {
  return entry.project ??
    entry.reports?.find((item) => item.reportPath === testCase.reportPath)
      ?.project ?? entry.label;
}

function caseRow(pagesUrl, { entry, testCase }, detail) {
  const target = caseTarget(pagesUrl, entry, testCase);
  const screenshot = testCase.previewPath
    ? `<a href="${htmlAttribute(target)}"><img src="${htmlAttribute(reportUrl(pagesUrl, testCase.previewPath))}" alt="${htmlAttribute(testCase.name)}" width="160"></a>`
    : '—';
  return `| ${inlineCell(caseProject(entry, testCase))} | [${inlineCell(testCase.name)}](${target}) | ${screenshot} | ${inlineCell(detail)} | ${formatDuration(testCase.durationMs) || '—'} |`;
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
  const incompleteEntries = report.entries.filter(
    (entry) =>
      entry.status !== 'success' &&
      !failedCases.some(({ entry: failedEntry }) => failedEntry === entry),
  );
  const unreportedFailure =
    !allPassed &&
    failedCases.length === 0 &&
    incompleteEntries.length === 0;
  const needsAttention =
    failedCases.length + incompleteEntries.length + Number(unreportedFailure);
  const runUrl = report.workflowUrl;
  const links = [
    `**[Open the published HTML report](${reportUrl(pagesUrl, report.reportPath ?? `reports/${runId}/index.html`)})**`,
    ...(runUrl ? [`[Download the artifact](${runUrl}#artifacts)`] : []),
    `[Report history](${normalizedBaseUrl(pagesUrl).href})`,
  ].join(' · ');

  const sections = [
    `## ${summaryTitle} × Midscene · ${allPassed ? 'passed' : 'failure captured'}`,
    '',
    `**${allPassed ? '✅ ' : ''}${needsAttention} need attention · ${passedCases.length} passed**`,
    '',
    '**Models:** configured in Actions Secrets',
    '',
    links,
    '',
  ];

  if (needsAttention > 0) {
    sections.push(
      '### Needs attention',
      '',
      '| Shard | Case | Screenshot | Status / reason | Duration |',
      '|:--|:--|:--|:--|--:|',
      ...incompleteEntries.map((entry) =>
        `| ${inlineCell(entry.label)} | — | — | ❌ ${inlineCell(entry.status)}${runUrl ? ` · [Workflow run](${runUrl})` : ''} | — |`,
      ),
      ...(unreportedFailure
        ? [`| Workflow | — | — | ❌ ${inlineCell(producerResult === 'success' ? 'incomplete report' : producerResult)}${runUrl ? ` · [Workflow run](${runUrl})` : ''} | — |`]
        : []),
      ...failedCases
        .sort((left, right) =>
          Number(left.testCase.status === 'not-run') -
          Number(right.testCase.status === 'not-run'),
        )
        .map((item) =>
          caseRow(
            pagesUrl,
            item,
            `${item.testCase.status === 'not-run' ? '⏭️ Not run' : '❌ Failed'}: ${failureReason(item.testCase)}`,
          ),
        ),
      '',
    );
  } else if (allPassed) {
    sections.push(`🎉 All ${passedCases.length} cases passed.`, '');
  } else {
    sections.push('No cases were reported.', '');
  }

  sections.push(
    '<details>',
    `<summary>Appendix: passed cases (${passedCases.length})</summary>`,
    '',
    '| Shard | Case | Screenshot | Status | Duration |',
    '|:--|:--|:--|:--|--:|',
    ...passedCases.map((item) => caseRow(pagesUrl, item, '✅ Passed')),
    '',
    '</details>',
    '',
    'Click a screenshot or case name to open its exact step in the native Midscene report. A CI failure card appears when a shard stops before Midscene can capture a report.',
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
