import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('./', import.meta.url));
const planPath = resolve(root, 'review-plan.json');
const reportRoot = resolve(root, 'midscene_run/report');

export const normalizedText = (value) => String(value).toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
export const anchorPresent = (ocr, anchor) => normalizedText(ocr).includes(normalizedText(anchor));

function ocrScreenshot(reportDir, screenshot) {
  if (!screenshot?.path?.startsWith('./screenshots/')) throw new Error('Review screenshot is missing');
  return execFileSync('tesseract', [resolve(reportDir, screenshot.path), 'stdout',
    '-l', 'eng+chi_sim', '--psm', '11'], { encoding: 'utf8', timeout: 30_000,
    maxBuffer: 1_000_000, stdio: ['ignore', 'pipe', 'ignore'] });
}

export function evidenceFromReport(plan, report, reportDir, ocr = ocrScreenshot) {
  const scenario = plan.scenarios?.[0];
  if (!scenario) return { verified: false, reason: 'No PR-specific visual scenario was run' };
  if (!scenario.visualAnchor) return { verified: false, reason: 'No changed visual text anchor was planned' };
  const assertions = report.executions?.filter((execution) => execution.name?.startsWith('Assert - ')) || [];
  if (assertions.length < 2) return { verified: false, reason: 'Targeted visual assertion was not recorded' };
  const first = assertions[0].tasks?.find((task) => task.subType === 'Assert');
  const last = assertions.at(-1).tasks?.find((task) => task.subType === 'Assert');
  if (last?.output !== true) return { verified: false, reason: 'Targeted visual assertion did not pass' };
  const finalText = ocr(reportDir, last.uiContext?.screenshot);
  if (!anchorPresent(finalText, scenario.visualAnchor)) return { verified: false,
    reason: 'Changed visual text was absent from the final desktop screenshot' };
  if (scenario.action) {
    const initialText = ocr(reportDir, first?.uiContext?.screenshot);
    if (anchorPresent(initialText, scenario.visualAnchor)) return { verified: true,
      reason: 'Changed visual text independently confirmed by screenshot OCR before the planned action and afterward' };
  }
  return { verified: true, reason: 'Changed visual text independently confirmed by screenshot OCR' };
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const plan = JSON.parse(readFileSync(planPath, 'utf8'));
  try {
    const reportFile = readdirSync(reportRoot)
      .find((name) => /^computer-.*\.html\.[^.]+\.json$/.test(name));
    if (!reportFile) throw new Error('Native Midscene report was not found');
    const report = JSON.parse(readFileSync(resolve(reportRoot, reportFile), 'utf8'));
    plan.evidence = evidenceFromReport(plan, report, reportRoot);
  } catch (error) {
    plan.evidence = { verified: false, reason: `Screenshot evidence check unavailable: ${error.message}`.slice(0, 300) };
  }
  writeFileSync(planPath, JSON.stringify(plan));
  copyFileSync(planPath, resolve(root, 'midscene_run/review-plan.json'));
  console.log(`Independent PR screenshot evidence: ${plan.evidence.verified ? 'confirmed' : 'unconfirmed'}.`);
}
