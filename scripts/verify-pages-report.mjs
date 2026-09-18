#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
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

function expectedContentType(file) {
  if (file.endsWith('.html')) return 'text/html';
  if (file.endsWith('.png')) return 'image/png';
  if (file.endsWith('.jpg')) return 'image/jpeg';
  throw new Error(`No expected Content-Type is defined for ${file}`);
}

function normalizedBaseUrl(value) {
  const url = new URL(value);
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url;
}

async function checkEndpoint({ expectedType, url }, fetchImpl) {
  const response = await fetchImpl(url, {
    method: 'HEAD',
    redirect: 'follow',
    signal: AbortSignal.timeout(20_000),
  });
  const contentType = response.headers.get('content-type') ?? '';
  if (!response.ok || !contentType.toLowerCase().startsWith(expectedType)) {
    throw new Error(
      `${url}: HTTP ${response.status}, Content-Type ${contentType || '<missing>'}`,
    );
  }
  return `Verified HTTP ${response.status} ${expectedType}: ${url}`;
}

export async function verifyPublishedReport({
  fetchImpl = fetch,
  manifest,
  pagesUrl,
  runId,
}) {
  const report = manifest.reports.find((item) => item.runId === runId);
  if (!report) throw new Error(`Run ${runId} is absent from the report manifest`);
  if (!Array.isArray(report.files) || report.files.length === 0) {
    throw new Error(`Run ${runId} does not list published files`);
  }
  const baseUrl = normalizedBaseUrl(pagesUrl);
  const endpoints = [
    { url: baseUrl, expectedType: 'text/html' },
    ...report.files.map((file) => ({
      url: new URL(file, baseUrl),
      expectedType: expectedContentType(file),
    })),
  ];
  let failures = [];
  for (let attempt = 1; attempt <= 12; attempt += 1) {
    const results = await Promise.allSettled(
      endpoints.map((endpoint) => checkEndpoint(endpoint, fetchImpl)),
    );
    failures = results.filter((result) => result.status === 'rejected');
    if (failures.length === 0) {
      for (const result of results) process.stdout.write(`${result.value}\n`);
      return;
    }
    process.stdout.write(
      `Waiting for Pages propagation (${attempt}/12); ${failures.length} endpoint(s) are not ready.\n`,
    );
    if (attempt < 12) await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  throw new Error(
    `Pages endpoint verification failed: ${failures
      .map((result) => result.reason?.message ?? result.reason)
      .join('; ')}`,
  );
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const manifest = JSON.parse(
    await readFile(required(options, 'manifest'), 'utf8'),
  );
  await verifyPublishedReport({
    manifest,
    pagesUrl: required(options, 'pages-url'),
    runId: required(options, 'run-id'),
  });
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
}
