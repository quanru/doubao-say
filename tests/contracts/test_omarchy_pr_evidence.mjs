import assert from 'node:assert/strict';
import test from 'node:test';
import { anchorPresent, evidenceFromReport } from '../e2e/verify-omarchy-pr-evidence.mjs';

const plan = { scenarios: [{ visualAnchor: 'New welcome message', action: null }] };
const report = { executions: [
  { name: 'Assert - baseline', tasks: [{ subType: 'Assert', output: true,
    uiContext: { screenshot: { path: './screenshots/before.jpeg' } } }] },
  { name: 'Assert - new copy', tasks: [{ subType: 'Assert', output: true,
    uiContext: { screenshot: { path: './screenshots/after.jpeg' } } }] },
] };

test('OCR must independently see the changed text even if AI assertion passed', () => {
  assert.equal(anchorPresent('New welcome\nmessage', 'New welcome message'), true);
  assert.equal(evidenceFromReport(plan, report, '.', () => 'Sign in to get started').verified, false);
  assert.equal(evidenceFromReport(plan, report, '.', () => 'New welcome message').verified, true);
});

test('new PR copy visible before an unnecessary action is still screenshot evidence', () => {
  const planWithAction = { scenarios: [{ visualAnchor: 'Doubao preview account', action: 'Open the provider selector' }] };
  const evidence = evidenceFromReport(planWithAction, report, '.', () => 'Doubao preview account');
  assert.equal(evidence.verified, true);
  assert.match(evidence.reason, /before the planned action/);
});
