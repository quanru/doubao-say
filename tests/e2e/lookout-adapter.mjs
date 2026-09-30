// Trusted, bounded commands for the two pinned real-UI cases. No I/O on import.
// Plugin code is installed and executed only by the disposable-VM runner.
export const PIN = Object.freeze({
  repository: 'dpaluy/omarchy-lookout',
  sha: '9dfdfc49178c7e4521ca6b41910920bf17c54d80',
  id: 'dpaluy.lookout',
});

export function assertLookoutProfile(env) {
  if (env.REVIEW_PLUGIN_PROFILE !== 'lookout' ||
      env.REVIEW_PLUGIN_REPOSITORY !== PIN.repository ||
      env.REVIEW_PLUGIN_SHA !== PIN.sha || env.REVIEW_PLUGIN_ID !== PIN.id ||
      env.REVIEW_PLUGIN_OPEN_METHOD !== 'open') {
    throw new Error('LookOut adapter requires the trusted profile and exact reviewed repository, SHA, ID, and open IPC');
  }
}

export function createLookoutAdapter({ guest, env, record = () => {},
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now }) {
  assertLookoutProfile(env);
  let backup;
  let originalIdleEnabled;
  let touchedPlugin = false;
  let prepared = false;
  let baselineLastBreak;
  const log = (type, data = {}) => record({ at: new Date(now()).toISOString(), type, ...data });
  // Every SSH invocation has its own process timeout, including cleanup.
  const command = (text, deadline = Infinity) => {
    const timeout = Math.min(5000, deadline - now());
    if (timeout <= 0) throw new Error('LookOut observation deadline exceeded');
    return guest(text, timeout);
  };
  const poll = async (check, message) => {
    const deadline = now() + 10_000;
    let lastError;
    for (let attempt = 0; attempt < 40 && now() < deadline; attempt++) {
      try {
        const value = check(deadline);
        if (value) return value;
      } catch (error) { lastError = error; }
      if (now() < deadline) await sleep(Math.min(250, deadline - now()));
    }
    throw new Error(`${message}${lastError ? `: ${lastError.message}` : ''}`);
  };
  const status = deadline => {
    const raw = JSON.parse(command('omarchy-shell lookout status', deadline));
    if (!raw || !['working', 'idle', 'due', 'break', 'paused'].includes(raw.phase) ||
        !Number.isInteger(raw.remainingSec) || raw.remainingSec < 0 ||
        !(raw.lastBreakAt === null ||
          (typeof raw.lastBreakAt === 'string' && Number.isFinite(Date.parse(raw.lastBreakAt))))) {
      throw new Error('Invalid LookOut status');
    }
    // Do not retain call-app names or other unrelated runtime information.
    const state = { phase: raw.phase, remainingSec: raw.remainingSec, lastBreakAt: raw.lastBreakAt };
    log('status', { state });
    return state;
  };
  const layers = deadline => {
    const values = JSON.parse(command(
      `set -o pipefail; hyprctl -j layers | jq -c '[.. | objects | select(.namespace? == "lookout-break") | {namespace, x, y, w, h}]'`, deadline));
    if (!Array.isArray(values) || values.some(layer => !layer || layer.namespace !== 'lookout-break' ||
        !['x', 'y', 'w', 'h'].every(key => Number.isFinite(layer[key])) || layer.w <= 0 || layer.h <= 0)) {
      throw new Error('Invalid compositor layer observation');
    }
    log('compositor-layers', { namespace: 'lookout-break', count: values.length, layers: values });
    return values.length;
  };
  const settings = deadline => {
    const entries = JSON.parse(command(
      `jq -c '[.bar.layout[][] | select(type == "object") | select(.id == "dpaluy.lookout") | {intervalMin, breakSec, idleSec, waitWhenBusy, allowSkip}]' "$HOME/.config/omarchy/shell.json"`, deadline));
    if (!Array.isArray(entries) || entries.length !== 1) throw new Error('Expected exactly one LookOut bar entry');
    log('persisted-settings', { settings: entries[0] });
    return entries[0];
  };
  const idleStatus = deadline => {
    const value = JSON.parse(command('omarchy-shell idle status', deadline));
    if (!value || typeof value.enabled !== 'boolean' || value.stayAwakeStateLoaded !== true) {
      throw new Error('Omarchy idle state is not ready');
    }
    log('shell-idle', { enabled: value.enabled });
    return value.enabled;
  };
  const checkPhase = async ({ phase, overlay }) => {
    if (!['working', 'break'].includes(phase) || typeof overlay !== 'boolean' || (phase === 'break') !== overlay) {
      throw new Error('Invalid phase/overlay assertion');
    }
    let consecutive = 0;
    return poll(deadline => {
      try {
        const state = status(deadline);
        const count = layers(deadline);
        consecutive = state.phase === phase && (count > 0) === overlay ? consecutive + 1 : 0;
        // Avoid accepting a stale immediate sample after the Escape key event.
        return consecutive >= 3 && state;
      } catch (error) {
        consecutive = 0;
        throw error;
      }
    }, `Expected stable phase=${phase}, overlay=${overlay}`);
  };
  const requirePrepared = () => {
    if (!prepared) throw new Error('LookOut case has not been prepared');
  };

  return {
    async prepare({ allowSkip, breakSec }) {
      if (typeof allowSkip !== 'boolean' || breakSec !== 1800) {
        throw new Error('Only reviewed 1800-second setting combinations are allowed');
      }
      if (backup || prepared || touchedPlugin) throw new Error('A LookOut adapter may prepare only one case');
      const candidate = command('mktemp /tmp/lookout-review-shell.XXXXXX');
      if (!/^\/tmp\/lookout-review-shell\.[A-Za-z0-9]+$/.test(candidate)) throw new Error('Unexpected backup path');
      try {
        command(`cp "$HOME/.config/omarchy/shell.json" '${candidate}' && cmp -s "$HOME/.config/omarchy/shell.json" '${candidate}'`);
      } catch (error) {
        // Never promote an empty or failed backup to something cleanup restores.
        try { command(`rm -f '${candidate}'`); }
        catch (cleanupError) { throw new AggregateError([error, cleanupError], 'Backup failed and its temporary file could not be removed'); }
        throw error;
      }
      backup = candidate;
      log('backed-up-shell-config');
      originalIdleEnabled = await poll(deadline => ({ value: idleStatus(deadline) }), 'Omarchy idle state did not become ready').then(result => result.value);
      command('omarchy-shell idle disable');
      await poll(deadline => idleStatus(deadline) === false, 'Omarchy idle/screensaver was not disabled');
      touchedPlugin = true;
      command('omarchy-shell dpaluy.lookout close');
      const expected = { intervalMin: 45, breakSec, idleSec: 3600, waitWhenBusy: false, allowSkip };
      for (const [key, value] of Object.entries(expected)) {
        // Without --json Omarchy encodes false as a truthy string.
        command(`omarchy bar set dpaluy.lookout ${key} ${value} --json`);
      }
      await poll(deadline => {
        const actual = settings(deadline);
        return Object.entries(expected).every(([key, value]) => actual[key] === value);
      }, 'LookOut did not persist the exact typed review settings');
      // Real documented IPC resets paused/due/idle/working states. First skip
      // any old break, then verify the live service adopted the long duration.
      command('omarchy-shell lookout skip');
      command('omarchy-shell lookout start');
      const started = await checkPhase({ phase: 'break', overlay: true });
      if (started.remainingSec < 1780 || started.remainingSec > 1800) {
        throw new Error('Live LookOut service did not adopt the 1800-second break');
      }
      command('omarchy-shell lookout skip');
      const state = await checkPhase({ phase: 'working', overlay: false });
      if (state.remainingSec < 2680 || state.remainingSec > 2700) throw new Error('LookOut countdown was not reset to 45 minutes');
      baselineLastBreak = state.lastBreakAt;
      prepared = true;
      log('prepared', { pin: PIN, settings: expected, baselineLastBreak });
    },
    async assertPhase(input) { requirePrepared(); return checkPhase(input); },
    async assertAllowSkip({ value }) {
      requirePrepared();
      if (typeof value !== 'boolean') throw new Error('allowSkip must be boolean');
      await poll(deadline => settings(deadline).allowSkip === value, `Expected persisted allowSkip=${value}`);
    },
    assertSkipped() {
      requirePrepared();
      const state = status();
      if (state.phase !== 'working' || state.lastBreakAt !== baselineLastBreak ||
          state.remainingSec < 1800 || state.remainingSec > 2700 || layers() !== 0) {
        throw new Error('Skip did not preserve last-break history, remove the overlay, and restore the 45-minute interval');
      }
      log('skip-cross-check', { passed: true });
    },
    async endForCleanup() {
      requirePrepared();
      // This is cleanup, never evidence of a user bypassing the no-skip UI.
      command('omarchy-shell lookout skip');
      await checkPhase({ phase: 'working', overlay: false });
      log('cleanup-break', { mechanism: 'documented skip IPC' });
    },
    async cleanup() {
      prepared = false;
      const errors = [];
      const attempt = async (stage, operation) => {
        try { await operation(); return true; }
        catch (error) {
          errors.push(error);
          try { log('cleanup-error', { stage, message: String(error.message).slice(0, 500) }); }
          catch (recordError) { errors.push(recordError); }
          return false;
        }
      };
      if (touchedPlugin) {
        const skipped = await attempt('skip', () => command('omarchy-shell lookout skip'));
        const closed = await attempt('close', () => command('omarchy-shell dpaluy.lookout close'));
        const hidden = await attempt('verify-hidden', () => poll(deadline => layers(deadline) === 0, 'LookOut overlay remained after cleanup'));
        if (skipped && closed && hidden) touchedPlugin = false;
      }
      if (backup) {
        const copied = await attempt('restore-copy', () => command(`cp '${backup}' "$HOME/.config/omarchy/shell.json" && cmp -s '${backup}' "$HOME/.config/omarchy/shell.json"`));
        const reloaded = copied && await attempt('reload-config', () => command('omarchy-shell shell reloadConfig'));
        const verified = reloaded && await attempt('verify-restored-config', () => command(`cmp -s '${backup}' "$HOME/.config/omarchy/shell.json"`));
        if (verified && await attempt('remove-backup', () => command(`rm -f '${backup}'`))) {
          backup = undefined;
          await attempt('record-restoration', () => log('restored-shell-config', { verified: true }));
        }
      }
      if (originalIdleEnabled !== undefined) {
        const restored = await attempt('restore-idle', async () => {
          command(`omarchy-shell idle ${originalIdleEnabled ? 'enable' : 'disable'}`);
          await poll(deadline => idleStatus(deadline) === originalIdleEnabled, 'Omarchy idle state was not restored');
          log('restored-shell-idle', { enabled: originalIdleEnabled });
        });
        if (restored) originalIdleEnabled = undefined;
      }
      if (errors.length) throw new AggregateError(errors, 'LookOut cleanup failed; retained backup/state can be retried');
    },
  };
}

// Shared with the config and exercised through the actual Midscene case runner.
export async function prepareLookoutCase({ context, runId, onTeardown, adapter, input }) {
  if (context.lookoutCase) throw new Error('Prior LookOut case cleanup is incomplete');
  context.lookoutCase = { runId, adapter };
  onTeardown(async () => {
    await adapter.cleanup();
    if (context.lookoutCase?.adapter === adapter) context.lookoutCase = undefined;
  });
  await adapter.prepare(input);
}
