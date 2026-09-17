import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { resolve } from 'node:path';
import { ComputerAgent, agentForComputer } from '@midscene/computer';
import { defineNode, z } from '@midscene/test';
import { defineProjectSetup, defineTestProject } from '@midscene/test/config';
import { createMidsceneNodes } from '@midscene/test/midscene';

interface DesktopContext {
  agent: ComputerAgent;
  barConfigBackup?: string;
  barConfigExisted?: boolean;
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));
const stop = (child?: ChildProcess) => {
  if (child?.pid) {
    try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already exited */ }
  }
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
    const agent = await agentForComputer({
      xvfbResolution: omarchy ? '1280x800x24' : '1280x960x24',
      aiContexts: shell
        ? { aiAssert: 'Inspect the real Omarchy desktop through VNC. Judge only visible pixels; do not infer success from commands or configuration.' }
        : { aiAct: `Test the English Doubao Say GTK onboarding window${omarchy ? ' inside a real Omarchy VM shown through VNC' : ''}. Interact only with Doubao Say and use visible labels.` },
    });
    onTeardown(() => agent.destroy());
    const fluxbox = spawn('fluxbox', [], { detached: true, stdio: 'ignore', env: process.env });
    onTeardown(() => stop(fluxbox));
    await sleep(1000);
    if (omarchy) {
      const viewer = spawn('vncviewer', ['-FullScreen=1', '-RemoteResize=0', '-ViewOnly=0', '127.0.0.1:5905'], {
        detached: true, stdio: 'ignore', env: process.env,
      });
      onTeardown(() => stop(viewer));
      await sleep(4000);
    } else {
      const root = resolve(import.meta.dirname, '../../..');
      const fixture = spawn('/usr/bin/python3', ['tests/midscene/gtk_fixture.py'], {
        cwd: root, detached: true, stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env, GDK_BACKEND: 'x11', GSK_RENDERER: 'cairo', GTK_A11Y: 'none',
          PYTHONPATH: resolve(root, 'src'), XDG_CONFIG_HOME: resolve(root, '.midscene-config'),
        },
      });
      onTeardown(() => stop(fixture));
      await waitForFixture(fixture);
      await sleep(1000);
    }
    const context: DesktopContext = { agent };
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
const openSystemMenu = defineNode<typeof empty, void, DesktopContext>({
  name: 'shell.openSystemMenu', description: 'Open the real Omarchy system menu and focus one row.', inputSchema: empty,
  async execute() {
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
    context.barConfigExisted = guest('test -f "$HOME/.config/omarchy/shell.json" && echo yes || echo no') === 'yes';
    context.barConfigBackup = guest('mktemp /tmp/omarchy-midscene-bar.XXXXXX');
    if (context.barConfigExisted) guest(`cp "$HOME/.config/omarchy/shell.json" '${context.barConfigBackup}'`);
    guest('omarchy bar position left');
    await sleep(2000);
  },
});

export default defineTestProject<DesktopContext>({
  test: { maxConcurrency: 1, testTimeout: 8 * 60_000 },
  projects: [
    { name: 'ubuntu', setup, files: { include: ['cases/onboarding.yaml'] } },
    { name: 'omarchy-onboarding', setup, files: { include: ['cases/onboarding.yaml'] } },
    { name: 'omarchy-shell', setup, files: { include: ['cases/omarchy-shell.yaml'] } },
  ],
  nodes: [
    ...createMidsceneNodes<DesktopContext>({
      agentClass: ComputerAgent,
      agentProvider: (() => {
        const active = new Map<string, ComputerAgent>();
        return {
          getAgent(runId: string, { context }: { context: DesktopContext }) {
            active.set(runId, context.agent);
            return context.agent;
          },
          async releaseAgent(runId: string) {
            const agent = active.get(runId);
            if (!agent) throw new Error(`No Agent for Midscene case ${runId}`);
            active.delete(runId);
            await agent.destroy();
            if (!agent.reportFile) throw new Error(`No Agent report for Midscene case ${runId}`);
            return { reportPath: agent.reportFile };
          },
        };
      })(),
    }),
    openSystemMenu, closeSystemMenu, moveBarLeft,
  ],
});
