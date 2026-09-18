import { access, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import puppeteer from 'puppeteer-core';

import {
  findLatestTestReport,
} from '../../scripts/omarchy-shell-evidence.mjs';

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

const options = parseArguments(process.argv.slice(2));
const reportDirectory = path.resolve(
  options['report-dir'] || 'tests/e2e/midscene_run',
);
const primaryProject = options['primary-project'];
const auxiliaryProject = options['auxiliary-project'];
if (!primaryProject) throw new Error('Missing --primary-project');
if (!auxiliaryProject) throw new Error('Missing --auxiliary-project');

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

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

try {
  for (const [projectName, outputName, required] of [
    [primaryProject, 'report-preview.png', true],
    [auxiliaryProject, 'auxiliary-report-preview.png', false],
  ]) {
    const report = await findLatestTestReport(reportDirectory, {
      projectName,
      required,
    });
    if (!report) {
      console.log(
        `Skipped ${projectName} preview because that project did not produce a report.`,
      );
      continue;
    }
    const runnerDump = report.run;
    if (!runnerDump) throw new Error('Midscene Test runner dump was not found');
    const previewUrl = new URL(pathToFileURL(report.file));
    previewUrl.hash = new URLSearchParams({ 'runner-step': 'last' }).toString();
    const outputFile = path.join(reportDirectory, outputName);
    await mkdir(path.dirname(outputFile), { recursive: true });

    const page = await browser.newPage();
    await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
    await page.goto(previewUrl.href, { waitUntil: 'networkidle0' });
    await page.waitForSelector(
      '[aria-label="Execution steps"] button.is-selected .runner-step-status',
    );
    await page.waitForSelector('.runner-detail-evidence-panel');
    await page.waitForFunction(() => {
      const buttons = [
        ...document.querySelectorAll(
          '[aria-label="Execution steps"] .runner-detail-step-group > button',
        ),
      ];
      const selected = document.querySelector(
        '[aria-label="Execution steps"] button.is-selected',
      );
      const selectedName = selected?.querySelector(
        '.runner-detail-step-copy strong',
      )?.textContent;
      const detailName = document.querySelector(
        '.runner-detail-evidence-heading h2',
      )?.textContent;
      return (
        buttons.length > 0 &&
        selected === buttons.at(-1) &&
        Boolean(selectedName) &&
        selectedName === detailName
      );
    });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: outputFile, type: 'png' });
    await page.close();
    console.log(
      `Captured final Midscene report node (${runnerDump.status}): ${outputFile}`,
    );
  }
} finally {
  await browser.close();
}
