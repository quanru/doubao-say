import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveReview } from './resolve-omarchy-review.mjs';

test('discovers a panel plugin without project settings', () => {
  const result = resolveReview({ id: 'example.panel', name: 'Example Panel', kinds: ['panel'] });
  assert.equal(result.method, 'summon');
  assert.match(result.assertion, /Example Panel/);
});

test('discovers a bar widget and preserves its section', () => {
  const result = resolveReview({ id: 'example.widget', kinds: ['bar-widget'], barWidget: { defaultSection: 'left' } });
  assert.equal(result.method, 'inspectBar');
  assert.equal(result.section, 'left');
});

test('requires a visual adapter for headless services', () => {
  assert.throws(() => resolveReview({ id: 'example.service', kinds: ['service'] }), /no generic visual entry point/);
  assert.equal(resolveReview({ id: 'example.service', kinds: ['service'] }, { method: 'launch', assertion: 'Window visible' }).method, 'launch');
});

test('rejects settings that disagree with the exact commit manifest', () => {
  assert.throws(() => resolveReview({ id: 'example.widget', kinds: ['bar'] }, { id: 'wrong.id' }), /does not match/);
});
