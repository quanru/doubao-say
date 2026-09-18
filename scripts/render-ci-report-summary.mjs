#!/usr/bin/env node

import { appendFile, readFile } from 'node:fs/promises';
import process from 'node:process';

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
  url.hash = new URLSearchParams({ 'runner-step': stepId }).toString();
  return url.href;
}

function markdownCell(value) {
  return String(value)
    .replaceAll('\\', '\\\\')
    .replaceAll('|', '\\|')
    .replaceAll('[', '\\[')
    .replaceAll(']', '\\]')
    .replaceAll('\n', ' ');
}

function entryResult(entry) {
  const parts = [];
  if (entry.scenarios.total > 0) {
    parts.push(
      `${entry.scenarios.passed}/${entry.scenarios.total} scenarios passed`,
    );
  }
  if (entry.assertions.total > 0) {
    parts.push(
      `${entry.assertions.passed}/${entry.assertions.total} visual assertions passed`,
    );
  }
  return `**${entry.label}: ${parts.join(' · ') || 'report captured'}.**`;
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
  const historyUrl = normalizedBaseUrl(pagesUrl).href;
  const links = [
    ...report.entries.map(
      (entry) =>
        `[Open ${entry.label}](${reportUrl(pagesUrl, entry.reportPath)})`,
    ),
    `[Report history](${historyUrl})`,
  ].join(' · ');
  const caseTables = report.entries.map((entry) => {
    if (!Array.isArray(entry.cases) || entry.cases.length === 0) {
      throw new Error(`${entry.label} does not contain case evidence`);
    }
    const rows = entry.cases.map((testCase) => {
      if (!testCase.description || !testCase.descriptionKind) {
        throw new Error(`${testCase.name} does not contain node text evidence`);
      }
      const target = stepUrl(pagesUrl, entry.reportPath, testCase.stepId);
      const image = reportUrl(pagesUrl, testCase.previewPath);
      const status = testCase.status === 'success' ? '✅ Passed' : '❌ Failed';
      const evidence =
        testCase.status === 'success'
          ? 'Last screenshot'
          : 'First failing screenshot';
      const descriptionLabel = {
        ai: '**AI:** ',
        error: '**Error:** ',
        result: '**Result:** ',
      }[testCase.descriptionKind];
      return `| ${status} | [${markdownCell(testCase.name)}](${target}) | [![${evidence}: ${markdownCell(testCase.name)}](${image})](${target}) | ${descriptionLabel}${markdownCell(testCase.description)} |`;
    });
    return `### ${entry.label}

| Result | Case | Node screenshot | AI response / error |
|:--|:--|:--|:--|
${rows.join('\n')}`;
  })
    .join('\n\n');

  return `## ${title}

${report.entries.map(entryResult).join('\n\n')}

${links}

${caseTables}

Each image is the original page screenshot used by that node. Click a case name or image to open the exact Midscene Test node and Agent replay.
`;
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
