import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { tsImport } from 'tsx/esm/api';
import { collectWorkflowDocument } from '@midscene/test';
import { assertPr48Profile, createPr48Adapter, PR48_PIN, validatePr48Status, matchPr48Surfaces } from './pr48-adapter.mjs';

const env = { PR48_REGRESSION_PROFILE: 'matched-pr48', GITHUB_EVENT_NAME: 'workflow_dispatch',
  GITHUB_REF: 'refs/heads/research/omarchy-plugin-visual-review' };
const ready = variant => ({ schema_version: 1, variant, pid: 1234, ready: true, phase: 'ready', recording_state: 'idle',
  overlay_visible: false, start_attempts: 0, asr_connect_calls: 0, overlay_show_calls: 0,
  paste_calls: 0, result: '', error: null, diagnostics: [] });
const failed = { ...ready('before'), phase: 'start_failed', start_attempts: 1,
  error: { type: 'ValueError', message: 'Unsupported diagnostic stage: audio_delegated',
    traceback: 'prime_recording > diagnostics.py > add' } };
const listening = { ...ready('after'), phase: 'listening', recording_state: 'recording',
  overlay_visible: true, start_attempts: 1, asr_connect_calls: 1, overlay_show_calls: 1,
  diagnostics: ['audio_delegated', 'gesture_confirmed', 'connection_requested', 'connected'] };
const finished = { ...listening, phase: 'finished', recording_state: 'idle', overlay_visible: false,
  paste_calls: 1, result: 'Synthetic PR48 dictation completed.' };

test('compositor accepts the production fallback only for exact mapped overlay PID/title', () => {
  const client = { title: 'Doubao Say overlay', class: 'python3', pid: 1234,
    mapped: true, hidden: false, visible: true, at: [440, 370], size: [400, 86] };
  const layer = { namespace: 'doubao-say-overlay', pid: 1234, x: 440, y: 690, w: 400, h: 86 };
  assert.equal(matchPr48Surfaces({ pid: 1234, layers: [], clients: [client] }).count, 1);
  assert.equal(matchPr48Surfaces({ pid: 1234, layers: [layer], clients: [] }).count, 1);
  for (const override of [{pid: 4321}, {title: 'PR48 isolated voice test'}, {mapped: false},
    {hidden: true}, {visible: false}]) {
    assert.equal(matchPr48Surfaces({pid: 1234, layers: [], clients: [{...client, ...override}]}).count, 0);
  }
  assert.equal(matchPr48Surfaces({pid: 1234, layers: [{...layer, pid: 4321}], clients: []}).count, 0);
  assert.throws(() => matchPr48Surfaces({pid: 1234, layers: [], clients: [{...client, size: [0, 86]}]}), /geometry/);
  assert.equal(matchPr48Surfaces({pid: 1234, layers: [layer], clients: [client]}).count, 2,
    'caller rejects ambiguous duplicate surfaces instead of passing');
});

test('PR48 profile rejects unapproved route before I/O', () => {
  assert.doesNotThrow(() => assertPr48Profile(env));
  for (const override of [{ PR48_REGRESSION_PROFILE: '' }, { GITHUB_EVENT_NAME: 'pull_request' },
    { GITHUB_REF: 'refs/heads/main' }]) {
    let called = false;
    assert.throws(() => createPr48Adapter({ env: { ...env, ...override }, guest: () => { called = true; } }), /bounded manual/);
    assert.equal(called, false);
  }
});

test('before proof requires production exception, zero overlay/connect, and exactly one start', () => {
  assert.equal(validatePr48Status(failed, 'before', 'start_failed'), true);
  for (const override of [{ start_attempts: 2 }, { overlay_visible: true }, { asr_connect_calls: 1 },
    { overlay_show_calls: 1 }, { paste_calls: 1 }, { recording_state: 'recording' },
    { error: { ...failed.error, type: 'ImportError' } }, { error: { ...failed.error, traceback: 'different code' } }]) {
    assert.equal(validatePr48Status({ ...failed, ...override }, 'before', 'start_failed'), false);
  }
});

test('after proof requires accepted diagnostic plus real state and exactly one delivery', () => {
  assert.equal(validatePr48Status(listening, 'after', 'listening'), true);
  assert.equal(validatePr48Status(finished, 'after', 'finished'), true);
  for (const override of [{ diagnostics: [] }, { start_attempts: 2 }, { overlay_visible: false },
    { asr_connect_calls: 0 }, { recording_state: 'starting' }]) {
    assert.equal(validatePr48Status({ ...listening, ...override }, 'after', 'listening'), false);
  }
  for (const override of [{ paste_calls: 2 }, { result: 'Something else' }, { overlay_visible: true },
    { recording_state: 'stopping' }]) {
    assert.equal(validatePr48Status({ ...finished, ...override }, 'after', 'finished'), false);
  }
});

test('invalid variants and out-of-order after never launch a guest process', async () => {
  const commands = [];
  const adapter = createPr48Adapter({ env, guest: text => { commands.push(text); return ''; } });
  for (const variant of ['after', '../before', '', 'unknown']) await assert.rejects(adapter.prepare({ variant }), /before then after/);
  assert.deepEqual(commands, []);
});

test('adapter launches each pinned revision once and verifies same harness hash', async () => {
  let active; let status; let idle = true; let clock = 0;
  const commands = [], events = [];
  const guest = command => {
    commands.push(command);
    if (command === 'omarchy-shell idle status') return JSON.stringify({ enabled: idle });
    if (/omarchy-shell idle (enable|disable)/.test(command)) { idle = command.endsWith('enable'); return ''; }
    if (command.includes('nohup setsid')) { active = command.includes('--variant before') ? 'before' : 'after'; status = ready(active); return ''; }
    if (command.endsWith('/status.json') && command.startsWith('cat ')) return JSON.stringify(status);
    if (command.endsWith('/provenance.json')) return JSON.stringify({ commit: PR48_PIN[active], harness_sha256: 'a'.repeat(64) });
    if (command.includes('control.json.tmp')) {
      const emitted = execFileSync('bash', ['-c', command.split(' > ')[0]], { encoding: 'utf8' });
      const request = JSON.parse(emitted);
      if (request.command === 'exit') assert.deepEqual(request, { id: 'teardown', command: 'exit' });
      else {
        assert.equal(request.id, `programmatic-${active}-${request.command}`);
        status = { ...(request.command === 'finish' ? finished : active === 'before' ? failed : listening), last_command_id: request.id };
      }
      return '';
    }
    if (command.includes('kill -0')) { status = {...status, overlay_visible:false}; return 'stopped'; }
    if (command.endsWith('/exit.json')) return JSON.stringify({ exit_code: 0, workers_stopped: true, result: active === 'before' ? 'expected_failure' : 'passed' });
    if (command.includes('hyprctl -j layers')) return JSON.stringify(status?.overlay_visible ? [{namespace: 'doubao-say-overlay', pid: 1234, x: 0, y: 0, w: 400, h: 86}] : []);
    if (command.includes('hyprctl -j clients')) return '[]';
    if (command.startsWith('grim ') || command.startsWith('cp ')) return '';
    throw new Error(`Unexpected command ${command}`);
  };
  const adapter = createPr48Adapter({ env, guest, record: event => events.push(event),
    sleep: async ms => { clock += ms; }, now: () => clock });
  await adapter.prepare({ variant: 'before' });
  await assert.rejects(adapter.prepare({ variant: 'before' }), /once/);
  await adapter.observe({variant:'before',phase:'ready'});
  await adapter.control({variant:'before',action:'start'});
  await assert.rejects(adapter.control({variant:'before',action:'start'}), /only once/);
  await adapter.observe({variant:'before',phase:'start_failed'});
  await adapter.prepare({ variant: 'after' });
  await assert.rejects(adapter.control({variant:'after',action:'finish'}), /precondition/);
  await adapter.observe({variant:'after',phase:'ready'});
  await adapter.control({variant:'after',action:'start'});
  await adapter.observe({variant:'after',phase:'listening'});
  await adapter.control({variant:'after',action:'finish'});
  await adapter.observe({variant:'after',phase:'finished'});
  await adapter.cleanup();
  assert.equal(commands.filter(command => command.includes('nohup setsid')).length, 2);
  assert.equal(events.filter(event => event.type === 'variant-cleanup').length, 2);
  assert.equal(idle, true);
  const count = commands.length;
  await adapter.cleanup();
  assert.equal(commands.length, count);
});

test('actual config and complete YAML enforce zero model calls and one programmatic start per variant', async () => {
  const { default: config } = await tsImport('./midscene.config.ts', import.meta.url);
  const registry = new Map(config.nodes.map(node => [node.name, node]));
  const sourcePath = 'cases/pr48-regression.yaml';
  const document = collectWorkflowDocument({ projectId: 'omarchy-pr48-regression', sourcePath,
    absolutePath: resolve(import.meta.dirname, sourcePath) }, { resolveNode: name => registry.get(name) });
  assert.equal(document.cases.length, 1);
  const steps = document.cases[0].definition.steps;
  for (const step of steps) assert.doesNotThrow(() => registry.get(step.node).inputSchema.parse(step.input));
  assert.equal(steps.filter(step => step.node === 'pr48.prepare').length, 2);
  assert.equal(steps.filter(step => step.node === 'pr48.command' && step.input.action === 'start').length, 2);
  assert.equal(steps.filter(step => step.node === 'pr48.command' && step.input.action === 'finish').length, 1);
  assert.equal(steps.filter(step => step.node.startsWith('ai')).length, 0);
  assert.equal(config.projects.find(project => project.name === 'omarchy-pr48-regression').retry, 0);
  assert.equal(registry.get('pr48.prepare').inputSchema.safeParse({ variant: 'before', command: 'anything' }).success, false);
});
