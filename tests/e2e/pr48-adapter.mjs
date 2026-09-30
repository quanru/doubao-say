// One trusted external harness, two exact product revisions, one fresh process each.
export const PR48_PIN = Object.freeze({
  before: 'c866b8fe03c18f0169b9327778ec9f620ac18095',
  after: 'ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2',
});

export function assertPr48Profile(env) {
  if (env.PR48_REGRESSION_PROFILE !== 'matched-pr48' ||
      env.GITHUB_EVENT_NAME !== 'workflow_dispatch' ||
      env.GITHUB_REF !== 'refs/heads/research/omarchy-plugin-visual-review') {
    throw new Error('PR48 requires the bounded manual matched-pr48 profile');
  }
}

export function validatePr48Status(value, variant, phase) {
  if (!value || value.schema_version !== 1 || value.variant !== variant ||
      typeof value.ready !== 'boolean' || typeof value.overlay_visible !== 'boolean' ||
      !['idle', 'starting', 'recording', 'stopping'].includes(value.recording_state) ||
      !['start_attempts', 'asr_connect_calls', 'overlay_show_calls', 'paste_calls'].every(
        key => Number.isSafeInteger(value[key]) && value[key] >= 0) ||
      !Array.isArray(value.diagnostics) || typeof value.result !== 'string') {
    throw new Error('Malformed PR48 status');
  }
  if (value.phase !== phase) return false;
  if (phase === 'ready') return value.ready && value.start_attempts === 0 &&
    value.recording_state === 'idle' && !value.overlay_visible && value.asr_connect_calls === 0 &&
    value.overlay_show_calls === 0 && value.paste_calls === 0 && value.error === null;
  if (phase === 'start_failed') return variant === 'before' && value.start_attempts === 1 &&
    value.recording_state === 'idle' && !value.overlay_visible && value.asr_connect_calls === 0 &&
    value.overlay_show_calls === 0 && value.paste_calls === 0 &&
    value.error?.type === 'ValueError' && /Unsupported diagnostic stage/.test(value.error.message) &&
    /prime_recording/.test(value.error.traceback) && /diagnostics\.py/.test(value.error.traceback);
  if (phase === 'listening') return variant === 'after' && value.start_attempts === 1 &&
    value.recording_state === 'recording' && value.overlay_visible && value.asr_connect_calls === 1 &&
    value.overlay_show_calls === 1 && value.paste_calls === 0 && value.error === null &&
    value.diagnostics.includes('audio_delegated');
  if (phase === 'finished') return variant === 'after' && value.start_attempts === 1 &&
    value.recording_state === 'idle' && !value.overlay_visible && value.asr_connect_calls === 1 &&
    value.overlay_show_calls === 1 && value.paste_calls === 1 && value.error === null &&
    value.result === 'Synthetic PR48 dictation completed.' && value.diagnostics.includes('audio_delegated');
  throw new Error('Unsupported PR48 observation phase');
}


export function matchPr48Surfaces({ layers, clients, pid }) {
  if (!Number.isSafeInteger(pid) || pid <= 0 || !Array.isArray(layers) || !Array.isArray(clients)) {
    throw new Error('Malformed PR48 compositor observation');
  }
  const ownLayers = layers.filter(value => value?.pid === pid && value.namespace === 'doubao-say-overlay');
  const ownClients = clients.filter(value => value?.pid === pid && value.title === 'Doubao Say overlay' &&
    value.mapped === true && value.hidden === false && value.visible === true);
  if (ownLayers.some(value => !['x', 'y', 'w', 'h'].every(key => Number.isFinite(value[key])) || value.w <= 0 || value.h <= 0) ||
      ownClients.some(value => typeof value.class !== 'string' || !Array.isArray(value.at) || value.at.length !== 2 ||
        !value.at.every(Number.isFinite) || !Array.isArray(value.size) || value.size.length !== 2 ||
        !value.size.every(size => Number.isFinite(size) && size > 0))) {
    throw new Error('Malformed PR48 surface geometry');
  }
  return { layers: ownLayers, clients: ownClients, count: ownLayers.length + ownClients.length };
}

export function createPr48Adapter({ guest, env, record = () => {},
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now }) {
  assertPr48Profile(env);
  let active;
  let idleEnabled;
  const visited = new Set();
  const commandsSent = new Set();
  const provenance = new Map();
  const log = (type, data = {}) => record({ at: new Date(now()).toISOString(), type, ...data });
  const command = text => guest(text, 10_000);
  const poll = async (check, message) => {
    const deadline = now() + 20_000;
    let error;
    for (let attempt = 0; attempt < 40 && now() < deadline; attempt++) {
      try { const result = check(); if (result) return result; } catch (caught) { error = caught; }
      await sleep(500);
    }
    throw new Error(`${message}${error ? `: ${error.message}` : ''}`);
  };
  const observations = () => {
    if (!active) throw new Error('No active PR48 variant');
    return JSON.parse(command(`cat /tmp/pr48-evidence/${active}/status.json`));
  };
  const surfaces = pid => matchPr48Surfaces({
    pid,
    layers: JSON.parse(command(`hyprctl -j layers | jq -c '[.. | objects | select(.namespace? == "doubao-say-overlay") | {namespace,pid,x,y,w,h}]'`)),
    clients: JSON.parse(command(`hyprctl -j clients | jq -c '[.[] | select(.title == "Doubao Say overlay") | {title,class,pid,mapped,hidden,visible,at,size}]'`)),
  });
  const stopActive = async () => {
    if (!active) return;
    const variant = active;
    const pid = observations().pid;
    command(`printf '%s' '{"id":"teardown","command":"exit"}' > /tmp/pr48-evidence/${variant}/control.json.tmp && mv /tmp/pr48-evidence/${variant}/control.json.tmp /tmp/pr48-evidence/${variant}/control.json`);
    try {
      await poll(() => command(`if kill -0 "$(cat /tmp/pr48-${variant}.pid)" 2>/dev/null; then echo running; else echo stopped; fi`) === 'stopped', 'PR48 process did not exit');
    } catch (error) {
      command(`kill "$(cat /tmp/pr48-${variant}.pid)" 2>/dev/null || true`);
      log('forced-cleanup', { variant });
      throw error;
    } finally { active = undefined; }
    const exit = JSON.parse(command(`cat /tmp/pr48-evidence/${variant}/exit.json`));
    if (exit.exit_code !== 0 || exit.workers_stopped !== true ||
        exit.result !== (variant === 'before' ? 'expected_failure' : 'passed')) {
      throw new Error('PR48 process did not exit with a complete verified outcome');
    }
    await poll(() => surfaces(pid).count === 0, 'PR48 overlay remained after cleanup');
    log('variant-cleanup', { variant, stopped: true, overlaySurfaces: 0, exit });
  };
  return {
    async prepare({ variant }) {
      if (!Object.hasOwn(PR48_PIN, variant) || visited.has(variant) ||
          (variant === 'after' && !visited.has('before'))) throw new Error('PR48 variants must run once, before then after');
      await stopActive();
      if (idleEnabled === undefined) {
        const idle = JSON.parse(command('omarchy-shell idle status'));
        if (typeof idle.enabled !== 'boolean') throw new Error('Unknown Omarchy idle state');
        idleEnabled = idle.enabled;
        command('omarchy-shell idle disable');
      }
      visited.add(variant);
      active = variant; // Register cleanup before launch, including partial failures.
      command(`export PYTHONPATH=/tmp/pr48-source/${variant}/src; export XDG_CONFIG_HOME=/tmp/pr48-config-${variant}; export PYTHONDONTWRITEBYTECODE=1; export LANGUAGE=en_US; export LANG=en_US.UTF-8; nohup setsid /usr/bin/python3 /tmp/pr48-harness.py --variant ${variant} --product-root /tmp/pr48-source/${variant} --timeout-seconds 420 >/tmp/pr48-${variant}.log 2>&1 </dev/null & echo $! >/tmp/pr48-${variant}.pid`);
      await poll(() => validatePr48Status(observations(), variant, 'ready'), 'PR48 harness did not become ready');
      const source = JSON.parse(command(`cat /tmp/pr48-evidence/${variant}/provenance.json`));
      if (source.commit !== PR48_PIN[variant] || !/^[a-f0-9]{64}$/.test(source.harness_sha256 ?? '')) {
        throw new Error('PR48 source provenance did not match exact revision');
      }
      provenance.set(variant, source);
      if (variant === 'after' && source.harness_sha256 !== provenance.get('before').harness_sha256) {
        throw new Error('PR48 variants used different harnesses');
      }
      log('prepared', { variant, source });
    },
    async control({ variant, action }) {
      if (variant !== active || !['start', 'finish'].includes(action) ||
          (action === 'finish' && variant !== 'after')) throw new Error('Invalid PR48 programmatic control');
      const id = `programmatic-${variant}-${action}`;
      if (commandsSent.has(id)) throw new Error('PR48 control can execute only once');
      const required = action === 'start' ? 'ready' : 'listening';
      if (!validatePr48Status(observations(), variant, required)) throw new Error('PR48 control precondition failed');
      commandsSent.add(id);
      const payload = JSON.stringify({ id, command: action });
      // All values are closed enums/derived strings; this invokes the same GLib
      // dispatch as the visible buttons without relying on a remote vision model.
      command(`printf '%s' '${payload}' > /tmp/pr48-evidence/${variant}/control.json.tmp && mv /tmp/pr48-evidence/${variant}/control.json.tmp /tmp/pr48-evidence/${variant}/control.json`);
      await poll(() => observations().last_command_id === id, 'PR48 programmatic control was not acknowledged');
      log('programmatic-control', { variant, action, id, source: 'control-file-to-shared-GLib-dispatch' });
    },
    async observe({ variant, phase }) {
      if (variant !== active || !['ready', 'start_failed', 'listening', 'finished'].includes(phase)) {
        throw new Error('PR48 observation does not match active variant');
      }
      let stable = 0;
      const expectedOverlay = phase === 'listening';
      try {
        await poll(() => {
          const state = observations();
          const mapped = surfaces(state.pid);
          stable = validatePr48Status(state, variant, phase) &&
            mapped.count === (expectedOverlay ? 1 : 0) ? stable + 1 : 0;
          return stable >= 2;
        }, `PR48 ${variant}/${phase} was not independently observed`);
      } catch (error) {
        try { command(`grim /tmp/pr48-evidence/${variant}/failed-${phase}.png; hyprctl -j layers > /tmp/pr48-evidence/${variant}/${phase}-layers.json; hyprctl -j clients > /tmp/pr48-evidence/${variant}/${phase}-clients.json`); }
        catch (captureError) { log('failure-screenshot-error', { variant, phase, message: captureError.message }); }
        log('failed-phase', { variant, phase, message: error.message });
        throw error;
      }
      command(`grim /tmp/pr48-evidence/${variant}/${phase}.png`);
      const state = observations();
      const mapped = surfaces(state.pid);
      log('verified-phase', { variant, phase, state, overlaySurfaces: mapped,
        screenshot: `${variant}/${phase}.png` });
      command(`cp /tmp/pr48-evidence/${variant}/status.json /tmp/pr48-evidence/${variant}/${phase}-status.json; hyprctl -j layers > /tmp/pr48-evidence/${variant}/${phase}-layers.json; hyprctl -j clients > /tmp/pr48-evidence/${variant}/${phase}-clients.json`);
    },
    async cleanup() {
      const errors = [];
      try { await stopActive(); } catch (error) { errors.push(error); }
      if (idleEnabled !== undefined) {
        try {
          command(`omarchy-shell idle ${idleEnabled ? 'enable' : 'disable'}`);
          const state = JSON.parse(command('omarchy-shell idle status'));
          if (state.enabled !== idleEnabled) throw new Error('Idle state restoration failed');
          log('restored-idle', { enabled: idleEnabled });
          idleEnabled = undefined;
        } catch (error) { errors.push(error); }
      }
      if (errors.length) throw new AggregateError(errors, 'PR48 cleanup failed');
    },
  };
}
