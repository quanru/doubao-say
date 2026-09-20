import { access, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import puppeteer from 'puppeteer-core';

import {
  findLatestTestReport,
} from '../../scripts/omarchy-shell-evidence.mjs';
import { reportCases } from '../../scripts/report-cases.mjs';

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
const projects = options.projects
  ? options.projects.split(',').map((value) => value.trim()).filter(Boolean)
  : [primaryProject, auxiliaryProject].filter(Boolean);
if (projects.length === 0) {
  throw new Error('Missing --projects or --primary-project');
}
const projectSlug = (projectName) => {
  const slug = projectName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  if (!slug) throw new Error(`Cannot build a preview filename for ${projectName}`);
  return slug;
};

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
  for (const [index, projectName] of projects.entries()) {
    const legacyOutputName = options.projects
      ? null
      : index === 0
        ? 'report-preview.png'
        : 'auxiliary-report-preview.png';
    const outputName =
      legacyOutputName ?? `report-preview-${projectSlug(projectName)}.png`;
    const report = await findLatestTestReport(reportDirectory, {
      projectName,
      required: options.projects ? true : index === 0,
    });
    if (!report) {
      console.log(
        `Skipped ${projectName} preview because that project did not produce a report.`,
      );
      continue;
    }
    const runnerDump = report.run;
    if (!runnerDump) throw new Error('Midscene Test runner dump was not found');
    const previewStep = runnerDump.status === 'success' ? 'last' : 'last-error';
    const previewUrl = new URL(pathToFileURL(report.file));
    previewUrl.hash = new URLSearchParams({
      'runner-step': previewStep,
    }).toString();
    const outputFile = path.join(reportDirectory, outputName);
    await mkdir(path.dirname(outputFile), { recursive: true });

    const page = await browser.newPage();
    await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
    await page.goto(previewUrl.href, { waitUntil: 'networkidle0' });
    await page.waitForSelector(
      '[aria-label="Execution steps"] button.is-selected .runner-step-status',
    );
    await page.waitForSelector('.runner-detail-evidence-panel');
    await page.waitForFunction((expectedStep) => {
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
        (expectedStep === 'last'
          ? selected === buttons.at(-1)
          : Boolean(selected?.querySelector('.runner-step-status.is-failed'))) &&
        Boolean(selectedName) &&
        selectedName === detailName
      );
    }, {}, previewStep);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: outputFile, type: 'png' });
    await page.close();
    console.log(
      `Captured Midscene report node ${previewStep} (${runnerDump.status}): ${outputFile}`,
    );

    for (const testCase of reportCases(runnerDump, projectName, {
      reportHtml: report.html,
    })) {
      const caseOutput = path.join(reportDirectory, testCase.previewFile);
      await writeFile(caseOutput, testCase.screenshot.bytes);
      console.log(
        `Extracted ${testCase.status} node screenshot for ${testCase.name} at ${testCase.stepId}: ${caseOutput}`,
      );
    }
  }
} finally {
  await browser.close();
}
