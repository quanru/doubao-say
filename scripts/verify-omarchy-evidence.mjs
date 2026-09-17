#!/usr/bin/env node

import { findShellReport } from './omarchy-shell-evidence.mjs';

const reportDirectory = process.argv[2];
if (!reportDirectory) {
  throw new Error('Usage: node scripts/verify-omarchy-evidence.mjs REPORT_DIR');
}

const { checks } = await findShellReport(reportDirectory);
const failed = checks.filter((check) => !check.passed);
console.log(`${checks.length - failed.length}/${checks.length} Omarchy visual assertions passed`);
if (failed.length) {
  throw new Error(`Failed visual assertions: ${failed.map((check) => check.label).join(', ')}`);
}
