import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { resolve } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { ComputerAgent, agentForComputer } from '@midscene/computer';
import { defineNode, z } from '@midscene/test';
import { defineProjectSetup, defineTestProject } from '@midscene/test/config';
import { createMidsceneNodes } from '@midscene/test/midscene';

interface DesktopContext {
  agent?: ComputerAgent;
  createAgent: () => Promise<ComputerAgent>;
  environment: 'ubuntu' | 'omarchy';
  shell: boolean;
  fixtureMode?: string;
  resetFixture?: (mode: string) => Promise<void>;
  barConfigBackup?: string;
  barConfigExisted?: boolean;
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));
const shellQuote = (value: string) => `'${value.replaceAll("'", `'"'"'`)}'`;
const stop = async (child?: ChildProcess) => {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise<void>((done) => {
    const timer = setTimeout(() => {
      try { process.kill(-child.pid!, 'SIGKILL'); } catch { /* already exited */ }
    }, 3000);
    child.once('exit', () => { clearTimeout(timer); done(); });
    try { process.kill(-child.pid!, 'SIGTERM'); }
    catch { clearTimeout(timer); done(); }
  });
};

function guest(command: string): string {
  const key = process.env.OMARCHY_SSH_KEY;
  if (!key) throw new Error('OMARCHY_SSH_KEY is required for shell tests');
  const env = [
    'export XDG_RUNTIME_DIR=/run/user/$(id -u);',
    'export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus;',
    'export HYPRLAND_INSTANCE_SIGNATURE=$(ls -t "$XDG_RUNTIME_DIR/hypr" | head -1);',
    'export WAYLAND_DISPLAY=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -name "wayland-*" ! -name "*.lock" -printf "%f\\n" | head -1);',
    'export OMARCHY_PATH=/usr/share/omarchy;',
    'export PATH="$OMARCHY_PATH/bin:$PATH";',
  ].join(' ');
  return execFileSync('ssh', [
    '-i', key, '-p', '2222', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'ConnectTimeout=10', '-o', 'LogLevel=ERROR',
    'omarchy@127.0.0.1', `${env} ${command}`,
  ], { encoding: 'utf8', timeout: 20_000 }).trim();
}

async function waitForFixture(child: ChildProcess): Promise<void> {
  await new Promise<void>((done, fail) => {
    let output = '';
    const timer = setTimeout(() => fail(new Error(`GTK fixture not ready:\n${output}`)), 15_000);
    const capture = (chunk: Buffer) => {
      output += chunk.toString();
      if (output.includes('READY: synthetic Doubao Say GTK fixture')) {
        clearTimeout(timer);
        done();
      }
    };
    child.stdout?.on('data', capture);
    child.stderr?.on('data', capture);
    child.once('error', (error) => { clearTimeout(timer); fail(error); });
    child.once('exit', (code) => {
      clearTimeout(timer);
      fail(new Error(`GTK fixture exited (${code}):\n${output}`));
    });
  });
}

const setup = defineProjectSetup<DesktopContext>({
  name: 'desktop',
  async setup({ project, onTeardown }) {
    const omarchy = project.name.startsWith('omarchy-');
    const shell = project.name === 'omarchy-shell' || project.name === 'omarchy-plugin-review' || project.name === 'omarchy-plugin-smoke';
    const polishing = project.name === 'ubuntu-polishing';
    let desktopReady = false;
    const createAgent = async () => {
      const agent = await agentForComputer({
        // Later case agents share the Xvfb display hosting Fluxbox and libnut.
        // The Omarchy harness owns a readiness-checked Xvfb process. Avoid the
        // ComputerAgent's fixed 500 ms Xvfb startup delay, which can race with
        // libnut initialization and terminate the whole Node process.
        headless: desktopReady || omarchy ? false : undefined,
        xvfbResolution: omarchy ? '1280x800x24' : '1280x960x24',
        // libnut and the VNC viewer may still hold X11 connections while the
        // Agent finalizes its report. Stop Xvfb only after this process exits.
        keepXvfbAliveUntilProcessExit: true,
        aiContexts: shell
          ? { aiAssert: 'Inspect the real Omarchy desktop through VNC. Judge only visible pixels; do not infer success from commands or configuration.' }
          : polishing ? { aiAct: 'Test the native polishing overlay using the separate Polishing overlay test controls window. Use visible button labels.' }
          : { aiAct: `Test the English Doubao Say GTK onboarding window${omarchy ? ' inside a real Omarchy VM shown through VNC' : ''}. Interact only with Doubao Say and use visible labels.` },
      });
      desktopReady = true;
      return agent;
    };
    const context: DesktopContext = {
      agent: await createAgent(),
      createAgent,
      environment: omarchy ? 'omarchy' : 'ubuntu',
      shell,
    };
    onTeardown(() => context.agent?.destroy());
    const fluxbox = spawn('fluxbox', [], { detached: true, stdio: 'ignore', env: process.env });
    onTeardown(() => stop(fluxbox));
    await sleep(1000);
    if (omarchy) {
      const viewer = spawn('vncviewer', ['-FullScreen=1', '-RemoteResize=0', '-ViewOnly=0', '127.0.0.1:5905'], {
        detached: true, stdio: 'ignore', env: process.env,
      });
      onTeardown(() => stop(viewer));
      await sleep(4000);
      if (!shell) {
        // Long model retries can outlast Omarchy's idle screensaver and hide
        // the GTK fixture from the VNC screenshots used by visual assertions.
        guest('omarchy-shell idle disable');
        const stopGuestFixture = () => {
          guest([
            'if test -s /tmp/doubao-midscene-fixture.pid; then',
            'pid="$(cat /tmp/doubao-midscene-fixture.pid)";',
            'kill "$pid" >/dev/null 2>&1 || true;',
            'for wait_step in 1 2 3 4 5; do',
            'kill -0 "$pid" >/dev/null 2>&1 || break; sleep 0.2;',
            'done;',
            'kill -KILL "$pid" >/dev/null 2>&1 || true;',
            'fi;',
            'rm -f /tmp/doubao-midscene-fixture.pid',
          ].join(' '));
        };
        onTeardown(stopGuestFixture);
        context.resetFixture = async (mode) => {
          const encodedMode = Buffer.from(mode).toString('base64');
          const expectedTitle = mode.startsWith('runtime-')
            ? 'Synthetic dictation target'
            : 'Doubao Say';
          stopGuestFixture();
          guest(`rm -rf /tmp/doubao-midscene-config; mkdir -p /tmp/doubao-midscene-config; export PYTHONPATH='/home/omarchy/.config/omarchy/plugins/md.lifeos.doubao-say/src'; export XDG_CONFIG_HOME=/tmp/doubao-midscene-config; export PYTHONDONTWRITEBYTECODE=1; export DOUBAO_E2E_MODE_B64='${encodedMode}'; nohup setsid python3 '/home/omarchy/.config/omarchy/plugins/md.lifeos.doubao-say/tests/e2e/gtk_fixture.py' >/tmp/doubao-midscene-fixture.log 2>&1 </dev/null & echo $! >/tmp/doubao-midscene-fixture.pid`);
          for (let attempt = 0; attempt < 30; attempt++) {
            const ready = guest(`grep -q 'READY: synthetic Doubao Say GTK fixture' /tmp/doubao-midscene-fixture.log && hyprctl -j clients | jq -r --arg title ${shellQuote(expectedTitle)} '[.[] | select(.title == $title)] | length' || true`);
            if (ready === '1') return;
            await sleep(2000);
          }
          const fixtureLog = guest(
            'tail -n 80 /tmp/doubao-midscene-fixture.log 2>/dev/null || true',
          );
          throw new Error(
            `Omarchy GTK fixture did not become ready:\n${fixtureLog || '<empty fixture log>'}`,
          );
        };
      }
    } else {
      const root = resolve(import.meta.dirname, '../..');
      let fixture: ChildProcess | undefined;
      let configDirectory: string | undefined;
      const cleanup = async () => {
        await stop(fixture);
        fixture = undefined;
        if (configDirectory) {
          await rm(configDirectory, { recursive: true, force: true });
          configDirectory = undefined;
        }
      };
      onTeardown(cleanup);
      context.resetFixture = async (mode) => {
        await cleanup();
        configDirectory = await mkdtemp(resolve(tmpdir(), 'doubao-midscene-'));
        fixture = spawn('/usr/bin/python3', [polishing ? 'tests/e2e/polish_fixture.py' : 'tests/e2e/gtk_fixture.py'], {
          cwd: root, detached: true, stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env, GDK_BACKEND: 'x11', GSK_RENDERER: 'cairo', GTK_A11Y: 'none',
            PYTHONPATH: resolve(root, 'src'), XDG_CONFIG_HOME: configDirectory,
            DOUBAO_E2E_MODE_B64: Buffer.from(mode).toString('base64'),
          },
        });
        await waitForFixture(fixture);
        await sleep(1000);
      };
    }
    if (shell) {
      onTeardown(() => {
        try {
          if (context.barConfigBackup) {
            guest(`${context.barConfigExisted ? `cp '${context.barConfigBackup}' "$HOME/.config/omarchy/shell.json"` : 'rm -f "$HOME/.config/omarchy/shell.json"'}; omarchy-shell shell reloadConfig; rm -f '${context.barConfigBackup}'`);
          }
          guest('omarchy-shell shell hide omarchy.menu');
        } catch (error) {
          console.error('Could not restore Omarchy shell state:', error);
        }
      });
    }
    return context;
  },
});

const empty = z.strictObject({});
const fixtureMode = z.strictObject({
  mode: z.enum([
    'microphone-gate',
    'trigger-settings',
    'voice-test',
    'volcengine',
    'deepgram',
    'microphone-change',
    'shortcut-capture',
    'runtime-delivery',
    'runtime-cancel',
  ]),
});
const keyboardKey = z.strictObject({
  keyName: z.enum(['F8', 'Escape']),
});
const inputText = z.strictObject({
  target: z.string().min(1),
  value: z.string(),
  point: z.strictObject({ x: z.number(), y: z.number() }).optional(),
});
const tapPoint = z.strictObject({
  target: z.string().min(1),
  point: z.strictObject({ x: z.number(), y: z.number() }),
});
const triggerPreset = z.strictObject({
  preset: z.enum(['Disabled', 'F8']),
});
const prepareFixture = defineNode<typeof fixtureMode, void, DesktopContext>({
  name: 'fixture.prepare',
  description: 'Select deterministic synthetic state for this test case.',
  inputSchema: fixtureMode,
  execute({ context, input }) {
    context.fixtureMode = input.mode;
  },
});
const pressKeyboardKey = defineNode<typeof keyboardKey, void, DesktopContext>({
  name: 'computer.keyPress',
  description: 'Press a desktop shortcut through the active Midscene Computer Agent.',
  inputSchema: keyboardKey,
  async execute({ context, input }) {
    if (!context.agent) throw new Error('Midscene Computer Agent is not active');
    if (context.environment === 'omarchy') {
      guest(`wtype -k ${input.keyName}`);
    } else {
      await context.agent.aiKeyboardPress(input.keyName);
    }
  },
});
const inputTextField = defineNode<typeof inputText, void, DesktopContext>({
  name: 'computer.inputText',
  description:
    'Replace text in a visually located input through the active Midscene Computer Agent.',
  inputSchema: inputText,
  async execute({ context, input }) {
    if (!context.agent) throw new Error('Midscene Computer Agent is not active');
    if (context.environment === 'omarchy') {
      // Focus the input through the VNC device. The optional point is reserved
      // for a fixed-size fixture where the model repeatedly located the label
      // instead of the entry. Send text inside Wayland because X11 clipboard
      // typing stops at the VNC boundary on some runner combinations.
      if (input.point) {
        await context.agent.interface.inputPrimitives.pointer.tap(input.point);
      } else {
        await context.agent.aiTap(input.target);
      }
      await sleep(250);
      guest(
        `wtype -M ctrl -k a -m ctrl; wtype -d 35 ${shellQuote(input.value)}`,
      );
    } else {
      await context.agent.aiInput(input.target, {
        value: input.value,
        mode: 'replace',
      });
    }
  },
});
const tapFixedPoint = defineNode<typeof tapPoint, void, DesktopContext>({
  name: 'computer.tapPoint',
  description: 'Tap a fixed point in the 1280x800 Omarchy fixture.',
  inputSchema: tapPoint,
  async execute({ context, input }) {
    if (!context.agent) throw new Error('Midscene Computer Agent is not active');
    await context.agent.interface.inputPrimitives.pointer.tap(input.point);
  },
});
const selectTriggerPreset = defineNode<typeof triggerPreset, void, DesktopContext>({
  name: 'computer.selectTriggerPreset',
  description: 'Select a trigger preset through the GTK dropdown in the fixed Omarchy fixture.',
  inputSchema: triggerPreset,
  async execute({ context, input }) {
    if (!context.agent || context.environment !== 'omarchy') {
      throw new Error('Omarchy Computer Agent is not active');
    }
    await context.agent.interface.inputPrimitives.pointer.tap({ x: 640, y: 498 });
    await sleep(250);
    const keys = ['Home', ...Array(input.preset === 'F8' ? 6 : 0).fill('Down'), 'Return'];
    guest(keys.map((key) => `wtype -k ${key}`).join('; '));
    await sleep(250);
  },
});
const openSystemMenu = defineNode<typeof empty, void, DesktopContext>({
  name: 'shell.openSystemMenu', description: 'Open the real Omarchy system menu and focus one row.', inputSchema: empty,
  async execute() {
    guest('omarchy-shell shell hide omarchy.menu');
    guest('omarchy-shell shell summon omarchy.menu \'{"menu":"system"}\'');
    for (let attempt = 0; attempt < 15; attempt++) {
      if (guest('hyprctl -j layers | jq -r \'[.. | objects | select(.namespace? == "omarchy-menu")] | length\'') !== '0') {
        guest('wtype -k Down');
        await sleep(1000);
        return;
      }
      await sleep(1000);
    }
    throw new Error('Omarchy system menu did not open');
  },
});
const closeSystemMenu = defineNode<typeof empty, void, DesktopContext>({
  name: 'shell.closeSystemMenu', description: 'Close the Omarchy system menu.', inputSchema: empty,
  execute() { guest('omarchy-shell shell hide omarchy.menu'); },
});
const moveBarLeft = defineNode<typeof empty, void, DesktopContext>({
  name: 'shell.moveBarLeft', description: 'Back up Omarchy bar settings and dock the bar left.', inputSchema: empty,
  async execute({ context }) {
    if (!context.barConfigBackup) {
      context.barConfigExisted = guest('test -f "$HOME/.config/omarchy/shell.json" && echo yes || echo no') === 'yes';
      context.barConfigBackup = guest('mktemp /tmp/omarchy-midscene-bar.XXXXXX');
      if (context.barConfigExisted) guest(`cp "$HOME/.config/omarchy/shell.json" '${context.barConfigBackup}'`);
    }
    guest('omarchy bar position left');
    await sleep(2000);
  },
});
const seedReviewPlugin = defineNode<typeof empty, void, DesktopContext>({
  name: 'review.seedTodo', description: 'Seed one item through the plugin IPC before checking its visible behavior.', inputSchema: empty,
  execute() {
    const initialStatus = guest('omarchy-shell tathagat11.checklist-todo status');
    if (initialStatus === '1 todo') return;
    if (initialStatus !== '0 todos') throw new Error(`Unexpected Checklist Todo state before seeding: ${initialStatus}`);
    const result = guest('omarchy-shell tathagat11.checklist-todo add "Midscene review item" "Visual review description"');
    if (!result || result === 'unavailable') throw new Error(`Could not seed Checklist Todo: ${result}`);
    if (guest('omarchy-shell tathagat11.checklist-todo status') !== '1 todo') {
      throw new Error('Checklist Todo did not accept the seeded item');
    }
  },
});
const openReviewPlugin = defineNode<typeof empty, void, DesktopContext>({
  name: 'review.openTodo', description: 'Open the reviewed plugin in the real Omarchy shell.', inputSchema: empty,
  async execute() {
    guest('omarchy-shell tathagat11.checklist-todo open');
    await sleep(1000);
  },
});
const assertReviewPluginEmpty = defineNode<typeof empty, void, DesktopContext>({
  name: 'review.assertEmpty', description: 'Confirm the visual deletion persisted in plugin state.', inputSchema: empty,
  async execute() {
    const status = guest('omarchy-shell tathagat11.checklist-todo status');
    if (status !== '0 todos') throw new Error(`Checklist Todo item remains after the visual action: ${status}`);
    const savedState = '"$HOME/.local/state/tathagat11.checklist-todo/todos.json"';
    for (let attempt = 0; attempt < 10; attempt++) {
      try {
        if (guest(`jq -e '.version == 1 and .todos == []' ${savedState} >/dev/null && echo saved`) === 'saved') return;
      } catch { /* wait for the widget's 300 ms atomic save */ }
      await sleep(500);
    }
    throw new Error('Checklist Todo did not persist the empty list after the visual action');
  },
});
const openConfiguredReviewPlugin = defineNode<typeof empty, void, DesktopContext>({
  name: 'review.openConfigured', description: 'Open the exact-commit plugin through shell summon or its declared IPC method.', inputSchema: empty,
  async execute() {
    const id = process.env.REVIEW_PLUGIN_ID;
    const method = process.env.REVIEW_PLUGIN_OPEN_METHOD || 'open';
    if (!id || !/^[a-z0-9][a-z0-9._-]{2,127}$/.test(id)) throw new Error('Valid REVIEW_PLUGIN_ID is required');
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(method)) throw new Error('Invalid REVIEW_PLUGIN_OPEN_METHOD');
    let lastError: unknown;
    for (let attempt = 0; attempt < 20; attempt++) {
      try {
        const command = method === 'summon' || method === 'toggle'
          ? `omarchy-shell shell ${method} ${shellQuote(id)} '{}'`
          : `omarchy-shell ${shellQuote(id)} ${shellQuote(method)}`;
        guest(command);
        await sleep(1000);
        return;
      } catch (error) {
        lastError = error;
        await sleep(1000);
      }
    }
    throw new Error(`Plugin IPC did not become ready: ${String(lastError)}`);
  },
});

const productCaseFiles = [
  'cases/onboarding.yaml',
  'cases/onboarding-regressions.yaml',
  'cases/runtime.yaml',
] as const;

const productShardProjects = (environment: 'ubuntu' | 'omarchy') =>
  [1, 2, 3, 4].map((shard) => ({
    name: `${environment}-shard-${shard}`,
    retry: 2,
    setup,
    files: { include: productCaseFiles },
    tags: { include: [`shard-${shard}`] },
  }));

export default defineTestProject<DesktopContext>({
  test: { maxConcurrency: 1, testTimeout: 8 * 60_000 },
  // Retries are scoped to failed cases. Every attempt stays visible in the
  // official Midscene report, and agent acquisition resets its fixture.
  projects: [
    {
      name: 'ubuntu-polishing',
      retry: 2,
      setup,
      files: { include: ['cases/polishing.yaml'] },
    },
    ...productShardProjects('ubuntu'),
    ...productShardProjects('omarchy'),
    {
      name: 'ubuntu-providers',
      retry: 2,
      setup,
      files: { include: productCaseFiles },
      tags: { include: ['provider'] },
    },
    {
      name: 'omarchy-providers',
      retry: 2,
      setup,
      files: { include: productCaseFiles },
      tags: { include: ['provider'] },
    },
    {
      name: 'omarchy-shell',
      retry: 2,
      setup,
      files: { include: ['cases/omarchy-shell.yaml'] },
    },
    {
      name: 'omarchy-plugin-review',
      retry: 1,
      setup,
      files: { include: ['cases/omarchy-plugin-review.yaml'] },
    },
    {
      name: 'omarchy-plugin-smoke',
      retry: 1,
      setup,
      files: { include: ['cases/omarchy-plugin-smoke.yaml'] },
    },
  ],
  nodes: [
    ...createMidsceneNodes<DesktopContext>({
      agentClass: ComputerAgent,
      agentProvider: (() => {
        const active = new Map<string, { agent: ComputerAgent; context: DesktopContext }>();
        return {
          async getAgent(runId: string, execution) {
            const { context } = execution;
            const existing = active.get(runId);
            if (existing) return existing.agent;
            context.agent ??= await context.createAgent();
            await context.resetFixture?.(context.fixtureMode ?? '');
            if (context.environment === 'omarchy' && !context.shell) {
              // The full-screen TigerVNC viewer can return two stale black
              // frames after the guest fixture is replaced. A harmless click
              // on the app header focuses the viewer and forces a fresh frame
              // before the first visual node captures its screenshot.
              await context.agent.interface.inputPrimitives.pointer.tap({
                x: 640,
                y: 50,
              });
              await sleep(750);
            }
            active.set(runId, { agent: context.agent, context });
            return context.agent;
          },
          async releaseAgent(runId: string) {
            const entry = active.get(runId);
            if (!entry) throw new Error(`No Agent for Midscene case ${runId}`);
            active.delete(runId);
            const { agent, context } = entry;
            await agent.destroy();
            context.agent = undefined;
            context.fixtureMode = undefined;
            if (!agent.reportFile) throw new Error(`No Agent report for Midscene case ${runId}`);
            return { reportPath: agent.reportFile };
          },
        };
      })(),
    }),
    prepareFixture,
    pressKeyboardKey,
    inputTextField,
    tapFixedPoint,
    selectTriggerPreset,
    openSystemMenu,
    closeSystemMenu,
    moveBarLeft,
    seedReviewPlugin,
    openReviewPlugin,
    assertReviewPluginEmpty,
    openConfiguredReviewPlugin,
  ],
});
