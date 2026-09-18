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
  const previews = report.entries
    .map(
      (entry) => `### ${entry.label}

[![Final node from ${entry.label}, with its pass or error status](${reportUrl(
        pagesUrl,
        entry.previewPath,
      )})](${reportUrl(pagesUrl, entry.reportPath)})`,
    )
    .join('\n\n');
  const noun = report.entries.length === 1 ? 'preview' : 'previews';

  return `## ${title}

${report.entries.map(entryResult).join('\n\n')}

${links}

${previews}

Click the final-node ${noun} to inspect the complete Midscene Test ${
    report.entries.length === 1 ? 'report' : 'reports'
  }, screenshots, and Agent replay.
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
