import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const workflow = readFileSync('.github/workflows/midscene-omarchy-4.0.3.yml', 'utf8');
const runner = readFileSync('tests/e2e/run-omarchy-midscene.sh', 'utf8');
const config = readFileSync('tests/e2e/midscene.config.ts', 'utf8');
const environment = {
  GITHUB_EVENT_NAME: 'workflow_dispatch', REQUESTED_PROJECT: 'omarchy-plugin-smoke',
  MIDSCENE_PROJECT: 'omarchy-plugin-smoke',
  REVIEW_PLUGIN_REPOSITORY: 'dpaluy/omarchy-lookout',
  REVIEW_PLUGIN_SHA: '9dfdfc49178c7e4521ca6b41910920bf17c54d80',
  REQUESTED_PLUGIN_ID: 'dpaluy.lookout', REVIEW_PLUGIN_ID: 'dpaluy.lookout',
  REQUESTED_PLUGIN_OPEN_METHOD: 'open', REVIEW_PLUGIN_OPEN_METHOD: 'open', REVIEW_PLUGIN_PROFILE: 'lookout',
};
function evaluateGuard(source, marker, overrides = {}) {
  const directory = mkdtempSync(path.join(tmpdir(), 'lookout-dispatch-'));
  const output = path.join(directory, 'env');
  writeFileSync(output, '');
  try {
    const script = source.split(`# ${marker}_BEGIN`)[1].split(`# ${marker}_END`)[0];
    const result = spawnSync('bash', ['-euc', script], { env: { ...environment, GITHUB_ENV: output, ...overrides }, encoding: 'utf8' });
    return { status: result.status, output: readFileSync(output, 'utf8') };
  } finally { rmSync(directory, { recursive: true, force: true }); }
}

test('workflow selects the bounded trusted profile only for the exact manual LookOut target', () => {
  const selected = evaluateGuard(workflow, 'LOOKOUT_PROFILE_GUARD', { REVIEW_PLUGIN_PROFILE: '' });
  assert.equal(selected.status, 0);
  assert.match(selected.output, /^REVIEW_PLUGIN_PROFILE=lookout$/m);
  assert.match(selected.output, /^MIDSCENE_MODEL_RETRY_COUNT=0$/m);
  assert.match(selected.output, /^MIDSCENE_REPLANNING_CYCLE_LIMIT=4$/m);
  assert.match(selected.output, /^MIDSCENE_RATE_GATE_MAX_REQUESTS=32$/m);
  for (const override of [
    { GITHUB_EVENT_NAME: 'issues' }, { REQUESTED_PROJECT: 'all' },
    { REVIEW_PLUGIN_REPOSITORY: 'other/plugin' }, { REVIEW_PLUGIN_SHA: 'a'.repeat(40) },
    { REQUESTED_PLUGIN_ID: 'other.plugin' }, { REQUESTED_PLUGIN_OPEN_METHOD: 'auto' },
  ]) assert.notEqual(evaluateGuard(workflow, 'LOOKOUT_PROFILE_GUARD', override).status, 0, JSON.stringify(override));
  const ordinary = evaluateGuard(workflow, 'LOOKOUT_PROFILE_GUARD', {
    REVIEW_PLUGIN_REPOSITORY: 'other/plugin', REQUESTED_PLUGIN_ID: 'other.plugin',
    REVIEW_PLUGIN_ID: 'other.plugin', REVIEW_PLUGIN_PROFILE: '',
  });
  assert.equal(ordinary.status, 0);
  assert.equal(ordinary.output, '');
});

test('runner rejects mismatched or missing profiles before VM or secret setup', () => {
  assert.equal(evaluateGuard(runner, 'LOOKOUT_RUNNER_GUARD').status, 0);
  for (const override of [
    { MIDSCENE_PROJECT: 'omarchy-shell' }, { REVIEW_PLUGIN_PROFILE: '' },
    { REVIEW_PLUGIN_REPOSITORY: 'other/plugin' }, { REVIEW_PLUGIN_SHA: 'a'.repeat(40) },
    { REVIEW_PLUGIN_ID: 'other.plugin' }, { REVIEW_PLUGIN_OPEN_METHOD: 'auto' },
  ]) assert.notEqual(evaluateGuard(runner, 'LOOKOUT_RUNNER_GUARD', override).status, 0, JSON.stringify(override));
  assert.ok(runner.indexOf('# LOOKOUT_RUNNER_GUARD_BEGIN') < runner.indexOf('readonly SHIM_DIR='));
});

test('LookOut uses the curated case and one preflight attempt without changing the matrix', () => {
  assert.match(runner, /if \[\[ "\$\{REVIEW_PLUGIN_PROFILE:-\}" == lookout \]\]; then\n\s+cp tests\/e2e\/cases\/omarchy-lookout-review\.yaml tests\/e2e\/cases\/omarchy-plugin-smoke\.yaml\n\s+else\n\s+node tests\/e2e\/render-omarchy-plugin-smoke\.mjs/);
  assert.match(config, /name: 'omarchy-plugin-smoke',[\s\S]*?files: \{ include: \['cases\/omarchy-plugin-smoke\.yaml'\] \}/);
  assert.match(workflow, /retry_args=\(--retry 0\)/);
  assert.match(workflow, /timeout-minutes: \$\{\{ .*inputs\.project == 'omarchy-plugin-smoke'.*inputs\.plugin_repository == 'dpaluy\/omarchy-lookout'.*inputs\.plugin_sha == '9dfdfc49178c7e4521ca6b41910920bf17c54d80'.*inputs\.plugin_id == 'dpaluy.lookout'.*inputs\.plugin_open_method == 'open'.*25 \|\| 60 \}\}/);
  assert.match(workflow, /format\('\["\{0\}"\]', inputs.project\)/);
  assert.ok(workflow.indexOf('# LOOKOUT_PROFILE_GUARD_BEGIN') < workflow.indexOf('- name: Configure existing worker model'));
});
