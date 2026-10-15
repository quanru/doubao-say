import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import { mkdir, rm } from 'node:fs/promises';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { ComputerAgent, checkAccessibilityPermission, checkScreenRecordingPermission } from '@midscene/computer';
import { defineProjectSetup, defineTestProject } from '@midscene/test/config';
import { createMidsceneNodes } from '@midscene/test/midscene';
import { MacComputerDevice } from './macos-device';

interface MacContext {
  start: () => Promise<ComputerAgent>;
  stop: () => Promise<void>;
}

async function stopProcess(child?: ChildProcess): Promise<void> {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise<void>((done) => {
    const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
    child.once('exit', () => { clearTimeout(timer); done(); });
    child.kill('SIGTERM');
  });
}

const setup = defineProjectSetup<MacContext>({
  name: 'isolated-macos-settings',
  async setup({ onTeardown }) {
    if (process.platform !== 'darwin') throw new Error('macos-settings requires a logged-in macOS desktop');
    for (const name of ['MIDSCENE_MODEL_API_KEY', 'MIDSCENE_MODEL_NAME', 'MIDSCENE_MODEL_BASE_URL', 'MIDSCENE_MODEL_FAMILY']) {
      if (!process.env[name]) throw new Error(`Missing ${name}; visual tests were not run`);
    }
    for (const [name, check] of [
      ['Accessibility', checkAccessibilityPermission(false)],
      ['Screen Recording', checkScreenRecordingPermission(false)],
    ] as const) {
      if (!check.hasPermission) throw new Error(`${name} preflight failed: ${check.error ?? 'grant permission to the test terminal/runner'}`);
    }
    const app = resolve(process.env.DOUBAO_MIDSCENE_APP ?? '../../build/macos/midscene/Doubao Midscene Fixture.app');
    const id = execFileSync('/usr/libexec/PlistBuddy', ['-c', 'Print :CFBundleIdentifier', `${app}/Contents/Info.plist`], { encoding: 'utf8' }).trim();
    if (!/^md\.lifeos\.doubao-say\.midscene\.[a-f0-9]{32}$/.test(id)) throw new Error('Refusing a non-isolated application bundle');
    const lock = `${app}.running`;
    await mkdir(lock); // Refuse concurrent desktop cases using the same profile.
    let fixture: ChildProcess | undefined;
    let agent: ComputerAgent | undefined;
    const stop = async () => {
      try { await agent?.destroy(); }
      finally { agent = undefined; await stopProcess(fixture); fixture = undefined; }
    };
    onTeardown(async () => {
      try { await stop(); }
      finally {
        // These paths are owned by the randomly generated fixture bundle, never the installed app.
        try { execFileSync('/usr/bin/defaults', ['delete', id], { stdio: 'ignore' }); }
        catch { /* A setup failure may leave no preferences domain. */ }
        await rm(resolve(homedir(), 'Library/Application Support', id), { recursive: true, force: true });
        await rm(lock, { recursive: true, force: true });
      }
    });
    return {
      stop,
      async start() {
        await stop();
        fixture = spawn(`${app}/Contents/MacOS/Fixture`, [], {
          env: { ...process.env, DOUBAO_MIDSCENE_FIXTURE: '1' },
          stdio: ['ignore', 'pipe', 'pipe'],
        });
        const child = fixture;
        await new Promise<void>((done, fail) => {
          let output = '';
          const timer = setTimeout(() => finish(new Error('macOS fixture readiness timed out')), 15_000);
          const capture = (chunk: Buffer) => {
            output += chunk.toString();
            if (output.includes('READY: isolated macOS Midscene fixture')) finish();
          };
          const failed = () => finish(new Error('macOS fixture exited before readiness'));
          function finish(error?: Error) {
            clearTimeout(timer);
            child.stdout?.off('data', capture); child.stderr?.off('data', capture);
            child.off('error', failed); child.off('exit', failed);
            if (error) fail(error); else done();
          }
          child.stdout?.on('data', capture); child.stderr?.on('data', capture);
          child.once('error', failed); child.once('exit', failed);
        });
        const options = {
          headless: false,
          displayId: process.env.MIDSCENE_MACOS_DISPLAY_ID,
          aiContexts: {
            aiAct: 'Interact only with the foreground Doubao Say settings fixture. Never open other apps, sign in, record audio, test services, copy text, or change system settings. All account and transcript data is synthetic.',
            aiAssert: 'Judge the visible native Doubao Say settings window only. Do not infer UI success from fixture setup.',
          },
        };
        const device = new MacComputerDevice(options);
        try {
          await device.connect();
          agent = new ComputerAgent(device, options);
          return agent;
        } catch (error) {
          await device.destroy();
          throw error;
        }
      },
    };
  },
});

export default defineTestProject<MacContext>({
  test: { maxConcurrency: 1, testTimeout: 6 * 60_000 },
  projects: [{ name: 'macos-settings', retry: 0, setup, files: { include: ['cases/macos-settings.yaml'] } }],
  nodes: createMidsceneNodes<MacContext>({
    agentClass: ComputerAgent,
    agentProvider: (() => {
      const active = new Map<string, { agent: ComputerAgent; context: MacContext }>();
      return {
        async getAgent(runId: string, { context }) {
          const existing = active.get(runId);
          if (existing) return existing.agent;
          const agent = await context.start();
          active.set(runId, { agent, context });
          return agent;
        },
        async releaseAgent(runId: string) {
          const entry = active.get(runId);
          if (!entry) return; // Acquisition failures still run project cleanup.
          active.delete(runId);
          await entry.context.stop();
          if (!entry.agent.reportFile) throw new Error('Missing native visual report');
          return { reportPath: entry.agent.reportFile };
        },
      };
    })(),
  }),
});
