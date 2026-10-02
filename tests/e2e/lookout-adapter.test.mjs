import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { tsImport } from 'tsx/esm/api';
import { collectWorkflowDocument, defineNode, normalizeSteps, runWorkflowDocument, z } from '@midscene/test';
import { createLookoutAdapter, prepareLookoutCase, PIN } from './lookout-adapter.mjs';

const env = { REVIEW_PLUGIN_PROFILE: 'lookout', REVIEW_PLUGIN_REPOSITORY: PIN.repository,
  REVIEW_PLUGIN_SHA: PIN.sha, REVIEW_PLUGIN_ID: PIN.id, REVIEW_PLUGIN_OPEN_METHOD: 'open' };
const input = { allowSkip: true, breakSec: 1800 };

function mock(options = {}) {
  const commands = [], events = [], timeouts = [];
  let clock = 0;
  const state = { phase: 'working', remainingSec: 2700, lastBreakAt: null,
    layers: [], idleEnabled: options.idleEnabled ?? true,
    settings: { intervalMin: 45, breakSec: 45, idleSec: 60, waitWhenBusy: true, allowSkip: true },
    backup: undefined, backups: 0 };
  const originalSettings = { ...state.settings };
  const control = { override: options.override };
  const guest = (command, timeout) => {
    commands.push(command); timeouts.push(timeout);
    const overridden = control.override?.(command, state);
    if (overridden !== undefined) return overridden;
    if (command.startsWith('mktemp ')) return `/tmp/lookout-review-shell.Mock${++state.backups}`;
    if (command.startsWith('cp "$HOME')) { state.backup = { ...state.settings }; return ''; }
    if (command.startsWith("cp '/tmp/")) { state.settings = { ...state.backup }; return ''; }
    if (command.startsWith('cmp ') || command.startsWith('rm ') || command === 'omarchy-shell shell reloadConfig') return '';
    if (command === 'omarchy-shell idle status') return JSON.stringify({ enabled: state.idleEnabled, stayAwakeStateLoaded: true });
    if (command === 'omarchy-shell idle disable') { state.idleEnabled = false; return 'disabled'; }
    if (command === 'omarchy-shell idle enable') { state.idleEnabled = true; return 'enabled'; }
    if (command.startsWith('omarchy bar set ')) {
      const match = /^omarchy bar set dpaluy\.lookout (\w+) (\S+)( --json)?$/.exec(command);
      assert.ok(match, 'only bounded setting commands');
      // Emulate the real Omarchy CLI: absent --json produces a string.
      state.settings[match[1]] = match[3] ? JSON.parse(match[2]) : match[2];
      return '';
    }
    if (command.startsWith('jq -c ')) return JSON.stringify([state.settings]);
    if (command.includes('hyprctl -j layers')) return JSON.stringify(state.layers);
    if (command === 'omarchy-shell dpaluy.lookout close') return '';
    if (command === 'omarchy-shell lookout start') {
      state.phase = 'break'; state.remainingSec = state.settings.breakSec;
      state.layers = [{ namespace: 'lookout-break', x: 0, y: 0, w: 1280, h: 800 }];
      return '';
    }
    if (command === 'omarchy-shell lookout skip') {
      if (state.phase === 'break') { state.phase = 'working'; state.remainingSec = 2700; state.layers = []; }
      return '';
    }
    if (command === 'omarchy-shell lookout status') return JSON.stringify({ ...state, callApps: ['not-for-evidence'] });
    throw new Error(`Unrecognized mock command: ${command}`);
  };
  const adapter = createLookoutAdapter({ guest, env, record: event => events.push(event),
    sleep: async ms => { clock += ms; }, now: () => clock });
  return { adapter, guest, state, commands, timeouts, events, control, originalSettings,
    now: () => clock, sleep: async ms => { clock += ms; } };
}

for (const [key, value] of Object.entries({ REVIEW_PLUGIN_PROFILE: '', REVIEW_PLUGIN_REPOSITORY: 'other/repo',
  REVIEW_PLUGIN_SHA: '0'.repeat(40), REVIEW_PLUGIN_ID: 'other.id', REVIEW_PLUGIN_OPEN_METHOD: 'launch' })) {
  test(`rejects a mismatched ${key} before guest I/O`, () => {
    let called = false;
    assert.throws(() => createLookoutAdapter({ env: { ...env, [key]: value }, guest: () => { called = true; } }), /exact reviewed/);
    assert.equal(called, false);
  });
}

test('rejects optional timer/unreviewed setting values without guest I/O', async () => {
  for (const invalid of [{ ...input, breakSec: 5 }, { ...input, breakSec: 10 }, { ...input, allowSkip: 'false' }]) {
    const m = mock();
    await assert.rejects(m.adapter.prepare(invalid), /reviewed/);
    assert.deepEqual(m.commands, []);
  }
});

test('uses typed CLI values, verifies service state, and restores config and idle state', async () => {
  const m = mock();
  await m.adapter.prepare(input);
  assert.deepEqual(m.state.settings, { intervalMin: 45, breakSec: 1800, idleSec: 3600, waitWhenBusy: false, allowSkip: true });
  assert.equal(m.state.idleEnabled, false);
  m.adapter.assertSkipped();
  await m.adapter.cleanup();
  assert.deepEqual(m.state.settings, m.originalSettings);
  assert.equal(m.state.idleEnabled, true);
  assert.ok(m.events.some(event => event.type === 'restored-shell-config' && event.verified));
  assert.ok(m.events.some(event => event.type === 'compositor-layers' && event.layers[0]?.w === 1280));
  assert.ok(!JSON.stringify(m.events).includes('not-for-evidence'));
  assert.ok(m.timeouts.every(timeout => timeout > 0 && timeout <= 5000));
  const count = m.commands.length;
  await m.adapter.cleanup();
  assert.equal(m.commands.length, count, 'successful cleanup is idempotent');
});

test('does not enable idle when it was already disabled', async () => {
  const m = mock({ idleEnabled: false });
  await m.adapter.prepare(input);
  await m.adapter.cleanup();
  assert.equal(m.state.idleEnabled, false);
  assert.ok(!m.commands.includes('omarchy-shell idle enable'));
});

test('verifies no-skip persistence and a stable layer, then uses explicitly labeled cleanup IPC', async () => {
  const m = mock();
  await m.adapter.prepare({ ...input, allowSkip: false });
  m.guest('omarchy-shell lookout start');
  const priorClock = m.now();
  await m.adapter.assertPhase({ phase: 'break', overlay: true });
  assert.ok(m.now() - priorClock >= 500);
  await m.adapter.assertAllowSkip({ value: false });
  await m.adapter.endForCleanup();
  assert.equal(m.state.settings.allowSkip, false);
  assert.ok(m.events.some(event => event.type === 'cleanup-break'));
  await m.adapter.cleanup();
});

test('rejects assertions before preparation and changed break history', async () => {
  const m = mock();
  assert.throws(() => m.adapter.assertSkipped(), /not been prepared/);
  await assert.rejects(m.adapter.assertPhase({ phase: 'working', overlay: false }), /not been prepared/);
  await m.adapter.prepare(input);
  m.state.lastBreakAt = '2026-09-30T06:00:00.000Z';
  assert.throws(() => m.adapter.assertSkipped(), /preserve last-break history/);
  await m.adapter.cleanup();
});

test('rejects missing lastBreakAt instead of matching two undefined values', async () => {
  const m = mock({ override: command => command === 'omarchy-shell lookout status' ? JSON.stringify({ phase: 'break', remainingSec: 1800 }) : undefined });
  await assert.rejects(m.adapter.prepare(input), /Invalid LookOut status/);
  assert.ok(m.commands.length < 100, 'polling remains bounded');
  await m.adapter.cleanup();
});

test('does not accept empty, malformed, or zero-size mapped-layer evidence', async () => {
  for (const reply of ['', 'null', '{}', '[{"namespace":"lookout-break","x":0,"y":0,"w":0,"h":800}]']) {
    const m = mock();
    await m.adapter.prepare(input);
    m.control.override = command => command.includes('hyprctl -j layers') ? reply : undefined;
    await assert.rejects(m.adapter.assertPhase({ phase: 'working', overlay: false }), /Expected stable/);
    m.control.override = undefined;
    await m.adapter.cleanup();
  }
});

test('rejects duplicate settings entries and string booleans', async () => {
  for (const makeReply of [state => [state.settings, state.settings], state => [{ ...state.settings, allowSkip: 'true' }]]) {
    const m = mock({ override: (command, state) => command.startsWith('jq -c ') ? JSON.stringify(makeReply(state)) : undefined });
    await assert.rejects(m.adapter.prepare(input), /persist the exact typed/);
    await m.adapter.cleanup();
  }
});

test('failed initial backup can never overwrite shell config during cleanup', async () => {
  const m = mock({ override: command => { if (command.startsWith('cp "$HOME')) throw new Error('backup copy failed'); } });
  await assert.rejects(m.adapter.prepare(input), /backup copy failed/);
  await m.adapter.cleanup();
  assert.ok(!m.commands.some(command => command.startsWith("cp '/tmp/")));
  assert.ok(!m.commands.some(command => command.startsWith('omarchy ')));
});

test('partial prepare still restores configuration and idle', async () => {
  const m = mock({ override: command => { if (command.includes(' idleSec ')) throw new Error('setting write failed'); } });
  await assert.rejects(m.adapter.prepare(input), /setting write failed/);
  await m.adapter.cleanup();
  assert.deepEqual(m.state.settings, m.originalSettings);
  assert.equal(m.state.idleEnabled, true);
});

test('IPC cleanup failure cannot prevent config and idle restoration', async () => {
  const m = mock();
  await m.adapter.prepare(input);
  m.control.override = command => { if (command === 'omarchy-shell lookout skip') throw new Error('skip failed'); };
  await assert.rejects(m.adapter.cleanup(), /LookOut cleanup failed/);
  assert.deepEqual(m.state.settings, m.originalSettings);
  assert.equal(m.state.idleEnabled, true);
  assert.ok(m.commands.includes('omarchy-shell dpaluy.lookout close'));
  m.control.override = undefined;
  await m.adapter.cleanup();
});

test('failed restore retains the backup and reports failure until a successful retry', async () => {
  const m = mock();
  await m.adapter.prepare(input);
  const beforeCleanup = m.commands.length;
  m.control.override = command => { if (command.startsWith("cp '/tmp/")) throw new Error('restore failed'); };
  await assert.rejects(m.adapter.cleanup(), /LookOut cleanup failed/);
  assert.ok(!m.commands.slice(beforeCleanup).some(command => command.startsWith('rm ')));
  assert.ok(!m.events.some(event => event.type === 'restored-shell-config'));
  assert.equal(m.state.idleEnabled, true, 'independent idle restoration still runs');
  m.control.override = undefined;
  await m.adapter.cleanup();
  assert.deepEqual(m.state.settings, m.originalSettings);
});

const runLifecycle = async ({ failPrepare = false, failStep = false, failCleanup = false, cases = 1 } = {}) => {
  const models = [];
  const context = {};
  const prepare = defineNode({ name: 'prepare', inputSchema: z.strictObject({}), async execute(execution) {
    const m = mock(); models.push(m);
    if (failPrepare) m.control.override = command => { if (command.includes(' idleSec ')) throw new Error('prepare failure'); };
    await prepareLookoutCase({ context, runId: execution.case.runId, onTeardown: execution.onTeardown, adapter: m.adapter, input });
  } });
  const action = defineNode({ name: 'action', inputSchema: z.strictObject({}), execute() {
    const m = models.at(-1);
    if (failCleanup) m.control.override = command => { if (command.startsWith("cp '/tmp/")) throw new Error('cleanup failure'); };
    if (failStep) throw new Error('original visual assertion failure');
  } });
  const registry = { prepare, action };
  const result = await runWorkflowDocument({ documentId: 'test-document', projectId: 'test-project', sourcePath: 'mock-lifecycle.yaml',
    lifecycle: { beforeAll: [], beforeEach: [], afterEach: [], afterAll: [] },
    cases: Array.from({ length: cases }, (_, caseIndex) => ({ caseId: `case-${caseIndex}`, projectId: 'test-project', sourcePath: 'mock-lifecycle.yaml', caseIndex,
      definition: { name: `case ${caseIndex}`, steps: normalizeSteps([{ prepare: {} }, { action: {} }], name => registry[name]) } })),
  }, { context, resolveNode: name => registry[name], maxConcurrency: 1, retry: 0 });
  return { result, context, models };
};

test('real Midscene lifecycle preserves the failed step and a separate teardown failure', async () => {
  const { result, context, models } = await runLifecycle({ failStep: true, failCleanup: true });
  const run = result.cases[0].attempts[0];
  assert.equal(run.status, 'failed');
  assert.match(String(run.steps[1].error), /original visual assertion failure/);
  assert.equal(run.teardownErrors.length, 1);
  assert.ok(context.lookoutCase, 'failed cleanup retained for project-level retry');
  models[0].control.override = undefined;
  await context.lookoutCase.adapter.cleanup();
});

test('real Midscene lifecycle cleans partial preparation before any AI node', async () => {
  const { result, context, models } = await runLifecycle({ failPrepare: true });
  assert.equal(result.cases[0].attempts[0].status, 'failed');
  assert.equal(context.lookoutCase, undefined);
  assert.deepEqual(models[0].state.settings, models[0].originalSettings);
});

test('real Midscene lifecycle gives serial cases fresh adapters and successful cleanup', async () => {
  const { result, context, models } = await runLifecycle({ cases: 2 });
  assert.equal(result.cases.length, 2);
  assert.ok(result.cases.every(outcome => outcome.attempts[0].status === 'success'));
  assert.notEqual(models[0].adapter, models[1].adapter);
  assert.equal(context.lookoutCase, undefined);
  for (const m of models) assert.deepEqual(m.state.settings, m.originalSettings);
});

test('actual config registers all two-case YAML nodes and enforces strict bounded schemas', async () => {
  // Importing the config does not call setup, start a desktop, or run a plugin.
  const { default: config } = await tsImport('./midscene.config.ts', import.meta.url);
  const registry = new Map(config.nodes.map(node => [node.name, node]));
  const sourcePath = 'cases/omarchy-lookout-review.yaml';
  const document = collectWorkflowDocument({ projectId: 'omarchy-plugin-smoke', sourcePath,
    absolutePath: resolve(import.meta.dirname, sourcePath) }, { resolveNode: name => registry.get(name) });
  assert.equal(document.cases.length, 2);
  for (const item of document.cases) for (const step of item.definition.steps) {
    assert.doesNotThrow(() => registry.get(step.node).inputSchema.parse(step.input));
  }
  const schema = registry.get('lookout.prepare').inputSchema;
  assert.equal(schema.safeParse({ ...input, breakSec: 5 }).success, false);
  assert.equal(schema.safeParse({ ...input, command: 'anything' }).success, false);
  assert.equal(config.projects.find(project => project.name === 'omarchy-plugin-smoke').retry, 0);
});
