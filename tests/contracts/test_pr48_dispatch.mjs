import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const workflow = readFileSync('.github/workflows/midscene-omarchy-4.0.3.yml', 'utf8');
const runner = readFileSync('tests/e2e/run-omarchy-midscene.sh', 'utf8');
const config = readFileSync('tests/e2e/midscene.config.ts', 'utf8');
const BEFORE = 'c866b8fe03c18f0169b9327778ec9f620ac18095';
const AFTER = 'ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2';
const environment = {
  GITHUB_EVENT_NAME: 'workflow_dispatch',
  GITHUB_REF: 'refs/heads/research/omarchy-plugin-visual-review',
  REQUESTED_PROJECT: 'omarchy-pr48-regression', MIDSCENE_PROJECT: 'omarchy-pr48-regression',
  PR48_REGRESSION_PROFILE: 'matched-pr48', PR48_BEFORE_SHA: BEFORE, PR48_AFTER_SHA: AFTER,
  PR48_REQUEST_PLUGIN_OPEN_METHOD: 'auto', PR48_REQUEST_BOOTSTRAP: 'false',
};

function section(source, marker) {
  assert.equal(source.split(`# ${marker}_BEGIN`).length, 2, marker);
  return source.split(`# ${marker}_BEGIN`)[1].split(`# ${marker}_END`)[0];
}
function temporary(callback) {
  const directory = mkdtempSync(path.join(tmpdir(), 'pr48-contract-'));
  try { return callback(directory); }
  finally { rmSync(directory, { recursive: true, force: true }); }
}
function guard(source, marker, overrides = {}) {
  return temporary((directory) => {
    const output = path.join(directory, 'env');
    writeFileSync(output, '');
    const script = section(source, marker) + '\nprintf "CAPS=%s,%s,%s\\n" "${MIDSCENE_MODEL_RETRY_COUNT:-}" "${MIDSCENE_REPLANNING_CYCLE_LIMIT:-}" "${MIDSCENE_RATE_GATE_MAX_REQUESTS:-}"';
    const result = spawnSync('bash', ['-euc', script], {
      env: { ...environment, GITHUB_ENV: output, ...overrides }, encoding: 'utf8',
    });
    return { ...result, output: readFileSync(output, 'utf8') };
  });
}

const forbiddenPayloads = [
  { REVIEW_PLUGIN_REPOSITORY: 'quanru/doubao-say' }, { REVIEW_PLUGIN_SHA: AFTER },
  { PR48_REQUEST_PLUGIN_ID: 'md.lifeos.doubao-say' }, { REVIEW_PLUGIN_PROFILE: 'lookout' },
  { PR48_REQUEST_REVIEW_RUN_ID: 'review-48' }, { REVIEW_BASE_REPOSITORY: 'quanru/doubao-say' },
  { REVIEW_PR_NUMBER: '48' }, { PR48_REQUEST_VISIBLE_ASSERTION: 'Injected assertion' },
  { PR48_REQUEST_PLUGIN_OPEN_METHOD: 'open' }, { PR48_REQUEST_BOOTSTRAP: 'true' },
];

test('PR48 workflow guard binds an empty-payload manual run to the exact research branch', () => {
  const base = { PR48_REGRESSION_PROFILE: '' };
  const selected = guard(workflow, 'PR48_PROFILE_GUARD', base);
  assert.equal(selected.status, 0, selected.stderr);
  for (const line of [
    'PR48_REGRESSION_PROFILE=matched-pr48', `PR48_BEFORE_SHA=${BEFORE}`, `PR48_AFTER_SHA=${AFTER}`,
    'MIDSCENE_MODEL_RETRY_COUNT=0', 'MIDSCENE_REPLANNING_CYCLE_LIMIT=4', 'MIDSCENE_RATE_GATE_MAX_REQUESTS=32',
  ]) assert.ok(selected.output.split('\n').includes(line), line);
  for (const override of [
    { GITHUB_EVENT_NAME: 'issues' }, { GITHUB_EVENT_NAME: 'pull_request' },
    { GITHUB_REF: 'refs/heads/main' }, { GITHUB_REF: 'refs/tags/research/omarchy-plugin-visual-review' },
    { PR48_REGRESSION_PROFILE: 'matched-pr48' }, ...forbiddenPayloads,
  ]) assert.notEqual(guard(workflow, 'PR48_PROFILE_GUARD', { ...base, ...override }).status, 0, JSON.stringify(override));
  assert.notEqual(guard(workflow, 'PR48_PROFILE_GUARD', { REQUESTED_PROJECT: 'omarchy-shell' }).status, 0);
  const ordinary = guard(workflow, 'PR48_PROFILE_GUARD', { ...base, REQUESTED_PROJECT: 'omarchy-shell' });
  assert.equal(ordinary.status, 0);
  assert.equal(ordinary.output, '');
  assert.ok(workflow.indexOf('# PR48_PROFILE_GUARD_BEGIN') < workflow.indexOf('- name: Configure existing worker model'));
});

test('PR48 runner independently rejects wrong source, profile, branch, event, and review payload', () => {
  const selected = guard(runner, 'PR48_RUNNER_GUARD', {
    MIDSCENE_MODEL_RETRY_COUNT: '8', MIDSCENE_REPLANNING_CYCLE_LIMIT: '90', MIDSCENE_RATE_GATE_MAX_REQUESTS: '1000',
  });
  assert.equal(selected.status, 0, selected.stderr);
  assert.match(selected.stdout, /^CAPS=0,4,32$/m);
  for (const override of [
    { MIDSCENE_PROJECT: 'omarchy-shell' }, { PR48_REGRESSION_PROFILE: '' }, { PR48_REGRESSION_PROFILE: 'other' },
    { PR48_BEFORE_SHA: AFTER }, { PR48_AFTER_SHA: BEFORE },
    { GITHUB_EVENT_NAME: 'push' }, { GITHUB_REF: 'refs/heads/main' },
    { REVIEW_PLUGIN_ID: 'md.lifeos.doubao-say' }, { REVIEW_PLUGIN_OPEN_METHOD: 'launch' },
    ...forbiddenPayloads,
  ]) assert.notEqual(guard(runner, 'PR48_RUNNER_GUARD', override).status, 0, JSON.stringify(override));
  assert.ok(runner.indexOf('# PR48_RUNNER_GUARD_BEGIN') < runner.indexOf('readonly WORK_DIR='));
});

test('source payloads use pinned public archives and checksums, with no product installer', () => {
  const setup = section(runner, 'PR48_SOURCE_SETUP');
  assert.match(setup, /https:\/\/github\.com\/quanru\/doubao-say\/archive\/\$sha\.tar\.gz/);
  assert.match(setup, /dd3dce434ad5162c3cf4d807d774f087f7606a6c953ab1d9033abe48530577f1/);
  assert.match(setup, /36442aedc31ea2c4a99b6a3bde380252cf13c256253bebddf7e0d2c09512fc27/);
  assert.equal((setup.match(/sha256sum --check --status/g) || []).length, 2);
  assert.match(setup, /mkdir -p \/tmp\/pr48-source\/before \/tmp\/pr48-source\/after \/tmp\/pr48-evidence/);
  assert.match(setup, /'doubao-say-\$sha\/src'/);
  assert.match(setup, /tests\/e2e\/pr48_runtime_fixture\.py.*\/tmp\/pr48-harness\.py/);
  assert.match(setup, /sudo pacman -Sy --needed --noconfirm \$PR48_PACKAGES/);
  assert.match(setup, /gi\.require_version\('GdkX11', '4\.0'\)/);
  assert.doesNotMatch(setup, /install\.sh'|start\.sh'|plugin enable|plugin validate/);
  assert.match(setup, /monitor_count:length/);
  assert.match(setup, /iso_version.*OMARCHY_ISO_VERSION/);
});

test('PR48 has one VM, zero retries, four replans, 32 gated calls and one preflight', () => {
  assert.match(workflow, /timeout-minutes: \$\{\{ inputs\.project == 'omarchy-pr48-regression' && 25 \|\|/);
  assert.match(workflow, /\$\{PR48_REGRESSION_PROFILE:-\}" == matched-pr48 \]\]; then\n\s+# One preflight[^\n]*\n\s+retry_args=\(--retry 0\)/);
  assert.match(runner, /\$\{PR48_REGRESSION_PROFILE:-\}" == matched-pr48 \]\]; then\n\s+mkdir[^\n]*\n\s+export MIDSCENE_RATE_GATE_STATE_FILE=.*model-request-count\.json/);
  assert.match(runner, /omarchy-pr48-regression\)\n\s+# Leave time[^\n]*\n\s+timeout --signal=TERM --kill-after=10s 12m npm/);
  assert.match(config, /name: 'omarchy-pr48-regression',\s+retry: 0,/);
  assert.equal((runner.match(/VM_PID="\$\(cat/g) || []).length, 1);
  assert.match(workflow, /format\('\["\{0\}"\]', inputs.project\)/);
});

test('PR48 excludes bootstrap, external reports, callbacks, and Pages publishing', () => {
  assert.match(workflow, /name: Bootstrap hosted model\n\s+if: [^\n]*inputs\.project != 'omarchy-pr48-regression'/);
  for (const name of ['Obtain scoped Midscene model proxy token', 'Publish direct HTML report to Midscene', 'Complete Midscene review check']) {
    const step = workflow.split(`- name: ${name}\n`)[1].split('\n      - name:')[0];
    assert.match(step, /if: [^\n]*matrix\.project != 'omarchy-pr48-regression'/, name);
  }
  assert.match(workflow.split('  pages-report:\n')[1], /inputs\.project != 'omarchy-pr48-regression'/);
  assert.match(workflow.split('  report-bundle:\n')[1].split('    runs-on:')[0], /inputs\.project == '' \|\| inputs\.project == 'all'/);
  assert.match(workflow, /name: Upload installer evidence\n\s+if: [^\n]*matrix\.project != 'omarchy-pr48-regression'/);
});

test('bounded evidence cleanup is registered and runs before killing the VM on any exit', () => {
  const cleanup = runner.split('cleanup() {')[1].split('\ntrap cleanup EXIT')[0];
  assert.ok(cleanup.indexOf('collect_pr48_evidence') < cleanup.indexOf('kill "$VM_PID"'));
  assert.match(cleanup, /if ! collect_pr48_evidence; then[\s\S]*?result=1/);
  assert.match(runner, /timeout --signal=TERM --kill-after=5s 30s ssh/);
  assert.match(runner, /tests\/e2e\/midscene_run\/pr48/);
});

test('evidence packer copies synthetic records/screenshots while excluding controls and logs', () => temporary((directory) => {
  const root = path.join(directory, 'evidence');
  mkdirSync(path.join(root, 'before'), { recursive: true });
  for (const [name, data] of Object.entries({
    'before/status.json': '{"synthetic":true}', 'before/events.jsonl': '{}\n',
    'before/provenance.json': '{}', 'before/recording.png': 'synthetic PNG bytes',
    'environment.json': '{}', 'before/exit.json': '{"exit_code":0}',
    'before/start_failed-status.json': '{}', 'before/start_failed-layers.json': '[]',
    'before/exception.txt': 'Synthetic diagnostic exception',
    'before/control.json': '{}', 'before/runtime.log': 'not evidence',
  })) writeFileSync(path.join(root, name), data);
  const script = section(runner, 'PR48_EVIDENCE_PACK').replace("pathlib.Path('/tmp/pr48-evidence')", `pathlib.Path(${JSON.stringify(root)})`);
  const packed = spawnSync('python3', ['-c', script], { maxBuffer: 1024 * 1024 });
  assert.equal(packed.status, 0, packed.stderr.toString());
  const archive = path.join(directory, 'evidence.tar');
  const destination = path.join(directory, 'out');
  mkdirSync(destination);
  writeFileSync(archive, packed.stdout);
  const result = spawnSync('python3', ['-c', section(runner, 'PR48_EVIDENCE_UNPACK'), archive, destination], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(existsSync(path.join(destination, 'before/status.json')));
  assert.ok(existsSync(path.join(destination, 'before/recording.png')));
  assert.ok(!existsSync(path.join(destination, 'before/control.json')));
  assert.ok(!existsSync(path.join(destination, 'before/runtime.log')));
  assert.equal(JSON.parse(readFileSync(path.join(destination, 'collection.json'))).files.length, 9);
  assert.ok(existsSync(path.join(destination, 'before/exit.json')));
  assert.ok(existsSync(path.join(destination, 'before/exception.txt')));
}));

test('evidence unpacker rejects traversal, symbolic links, duplicates, and oversized files', () => temporary((directory) => {
  for (const attack of ['traversal', 'symlink', 'duplicate', 'oversized']) {
    const archive = path.join(directory, `${attack}.tar`);
    const destination = path.join(directory, attack);
    mkdirSync(destination);
    const built = spawnSync('python3', ['-c', `
import io, sys, tarfile
attack = sys.argv[2]
with tarfile.open(sys.argv[1], 'w') as archive:
    info = tarfile.TarInfo('../escape.json' if attack == 'traversal' else 'before/status.json')
    data = b'x' * (9 * 1024 * 1024 if attack == 'oversized' else 2)
    info.size = len(data)
    if attack == 'symlink':
        info.type = tarfile.SYMTYPE
        info.linkname = '/etc/passwd'
        info.size = 0
    archive.addfile(info, io.BytesIO(data))
    if attack == 'duplicate': archive.addfile(info, io.BytesIO(data))
`, archive, attack], { encoding: 'utf8' });
    assert.equal(built.status, 0, built.stderr);
    const result = spawnSync('python3', ['-c', section(runner, 'PR48_EVIDENCE_UNPACK'), archive, destination], { encoding: 'utf8' });
    assert.notEqual(result.status, 0, attack);
    assert.ok(!existsSync(path.join(directory, 'escape.json')));
  }
}));
