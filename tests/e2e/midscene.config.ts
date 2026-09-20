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
    const shell = project.name === 'omarchy-shell';
    const polishing = project.name === 'ubuntu-polishing';
    let desktopReady = false;
    const createAgent = async () => {
      const agent = await agentForComputer({
        // Later case agents share the Xvfb display hosting Fluxbox and libnut.
        headless: desktopReady ? false : undefined,
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
    'voice-test',
    'volcengine',
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
      // Midscene still finds and focuses the visual target. Send the text from
      // inside the Wayland guest because X11 clipboard typing stops at the VNC
      // boundary on some TigerVNC/GitHub runner combinations.
      await context.agent.aiTap(input.target);
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
      name: 'omarchy-shell',
      retry: 2,
      setup,
      files: { include: ['cases/omarchy-shell.yaml'] },
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
    openSystemMenu,
    closeSystemMenu,
    moveBarLeft,
  ],
});
