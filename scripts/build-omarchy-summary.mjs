#!/usr/bin/env node

import { appendFile } from 'node:fs/promises';
import { findShellReport } from './omarchy-shell-evidence.mjs';

const reportDirectory = process.argv[2];
const summaryFile = process.env.GITHUB_STEP_SUMMARY;
if (!reportDirectory || !summaryFile) {
  throw new Error(
    'Usage: GITHUB_STEP_SUMMARY=... node scripts/build-omarchy-summary.mjs REPORT_DIR',
  );
}

const { checks } = await findShellReport(reportDirectory);
const passed = checks.filter((check) => check.passed).length;
const runUrl = `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`;
const artifactUrl = process.env.REPORT_ARTIFACT_URL || runUrl;

await appendFile(
  summaryFile,
  `# Omarchy × Midscene · real desktop visual test

### ${passed}/${checks.length} visual assertions passed in Omarchy 4.0.3 / Hyprland

| Scene | Visible result | Midscene |
| --- | --- | --- |
${checks.map((check) => `| ${check.label} | ${check.passed ? '✅ Passed' : '❌ Failed'} | VLM screenshot assertion |`).join('\n')}

**Real VM:** official Omarchy ISO → KVM → Hyprland/Wayland → VNC → Midscene on X11.
**Evidence:** [Download the complete interactive HTML replay](${artifactUrl}) · [Open CI run](${runUrl}).

The replay contains the actual desktop screenshots, model judgments, and step timeline. The GitHub Pages job publishes a browser-ready showcase for successful main-branch runs.
`,
);

if (passed !== checks.length) process.exitCode = 1;
