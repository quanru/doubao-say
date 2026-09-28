import assert from 'node:assert/strict';
import test from 'node:test';
import { validatePlan, redactPatch } from '../e2e/plan-omarchy-pr-review.mjs';

test('review plan identifies runtime files not covered by scenarios', () => {
  const plan = validatePlan({ summary: 'Settings changed', scenarios: [{
    name: 'Open settings', action: 'Click Settings', assertion: 'New switch is visible', files: ['src/settings.py'],
  }] }, [{ filename: 'src/settings.py' }, { filename: 'src/runtime.py' }, { filename: 'README.md' }]);
  assert.deepEqual(plan.unverified, ['src/runtime.py']);
  assert.deepEqual(plan.changedFiles, ['src/settings.py', 'src/runtime.py', 'README.md']);
});

test('review plan rejects invented file coverage', () => {
  assert.throws(() => validatePlan({ summary: 'All changed', scenarios: [{
    name: 'Open settings', assertion: 'Settings visible', files: ['src/not-changed.py'],
  }] }, [{ filename: 'src/settings.py' }]));
});

test('review plan keeps one focused scenario and leaves the rest unverified', () => {
  const plan = validatePlan({ summary: 'Two screens changed', scenarios: [
    { name: 'Screen A', assertion: 'A visible', files: ['src/a.py'] },
    { name: 'Screen B', assertion: 'B visible', files: ['src/b.py'] },
  ] }, [{ filename: 'src/a.py' }, { filename: 'src/b.py' }]);
  assert.equal(plan.scenarios.length, 1);
  assert.deepEqual(plan.unverified, ['src/b.py']);
});

test('review planner redacts common credentials before model requests', () => {
  assert.equal(redactPatch('+ api_key = "sk-abcdefghijklmnopqrstuvwxyz"'), '+ api_key = "[REDACTED]"');
  assert.equal(redactPatch('+ Authorization: Bearer abcdefghijklmnopqrstuvwxyz'),
    '+ Authorization: Bearer [REDACTED]');
});
