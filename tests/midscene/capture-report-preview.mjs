import { access, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import puppeteer from 'puppeteer-core';

import {
  findLatestTestReport,
} from '../../scripts/omarchy-shell-evidence.mjs';

const reportDirectory = path.resolve(
  process.argv[2] || 'tests/midscene/midscene_run',
);
const outputFile = path.resolve(
  process.argv[3] || path.join(reportDirectory, 'report-preview.png'),
);

const candidates = [
  process.env.CHROME_BIN,
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

let executablePath;
for (const candidate of candidates) {
  try {
    await access(candidate);
    executablePath = candidate;
    break;
  } catch {}
}
if (!executablePath) {
  throw new Error('Chrome executable was not found');
}

const report = await findLatestTestReport(reportDirectory);
const runnerDump = report.run;
if (!runnerDump) throw new Error('Midscene Test runner dump was not found');
const previewUrl = new URL(pathToFileURL(report.file));
previewUrl.hash = new URLSearchParams({
  'runner-step': 'last',
  'runner-trace': 'page',
}).toString();
await mkdir(path.dirname(outputFile), { recursive: true });

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await page.goto(previewUrl.href, {
    waitUntil: 'networkidle0',
  });
  await page.waitForFunction(() => document.body.innerText.includes('AI TRACE'));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForFunction(() =>
    /Passed|Failed|Error/.test(document.body.innerText),
  );
  await page.screenshot({ path: outputFile, type: 'png' });
  console.log(
    `Captured final Midscene report node (${runnerDump.status}): ${outputFile}`,
  );
} finally {
  await browser.close();
}
