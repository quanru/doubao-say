import { spawn, type ChildProcess } from 'node:child_process';
import { resolve } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  it,
} from '@rstest/core';
import {
  type ComputerAgent,
  agentFromComputer,
} from '@midscene/computer';
import { runOnboardingFlow } from './onboarding-flow';
import {
  cancelAndRetrySignIn,
  revisitAccount,
  requireEnabledTrigger,
  togglePolishing,
  retryFailedEndpoint,
} from './onboarding-regressions';

const sleep = (milliseconds: number) =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

const stopProcessGroup = async (child?: ChildProcess) => {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise<void>((resolvePromise) => {
    const killTimer = setTimeout(() => {
      try {
        process.kill(-child.pid!, 'SIGKILL');
      } catch {
        // The process group has already exited.
      }
    }, 3000);
    child.once('exit', () => {
      clearTimeout(killTimer);
      resolvePromise();
    });
    try {
      process.kill(-child.pid!, 'SIGTERM');
    } catch {
      clearTimeout(killTimer);
      resolvePromise();
    }
  });
};

const waitForFixture = (child: ChildProcess) =>
  new Promise<void>((resolvePromise, rejectPromise) => {
    let diagnostics = '';
    const timeout = setTimeout(() => {
      rejectPromise(
        new Error(`GTK fixture did not become ready:\n${diagnostics}`),
      );
    }, 15_000);
    const capture = (chunk: Buffer) => {
      diagnostics += chunk.toString();
      if (diagnostics.includes('READY: synthetic Doubao Say GTK fixture')) {
        clearTimeout(timeout);
        resolvePromise();
      }
    };
    child.stdout?.on('data', capture);
    child.stderr?.on('data', capture);
    child.once('error', (error) => {
      clearTimeout(timeout);
      rejectPromise(error);
    });
    child.once('exit', (code, signal) => {
      clearTimeout(timeout);
      rejectPromise(
        new Error(
          `GTK fixture exited before ready (${code ?? signal}):\n${diagnostics}`,
        ),
      );
    });
  });

describe('Doubao Say onboarding', () => {
  let agent: ComputerAgent;
  let fluxbox: ChildProcess;
  let fixture: ChildProcess | undefined;
  let configDirectory: string | undefined;

  beforeAll(async () => {
    agent = await agentFromComputer({
      aiContexts: {
        aiAct:
          'You are testing the English Doubao Say GTK onboarding window. ' +
          'Interact only with the Doubao Say window and use visible labels.',
      },
      xvfbResolution: '1280x960x24',
    });

    fluxbox = spawn('fluxbox', [], {
      detached: true,
      stdio: 'ignore',
      env: process.env,
    });
    await sleep(1000);
  });

  beforeEach(async () => {
    configDirectory = await mkdtemp(resolve(tmpdir(), 'doubao-midscene-'));
    const repositoryRoot = resolve(import.meta.dirname, '../../..');
    fixture = spawn('/usr/bin/python3', ['tests/midscene/gtk_fixture.py'], {
      cwd: repositoryRoot,
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        GDK_BACKEND: 'x11',
        GSK_RENDERER: 'cairo',
        GTK_A11Y: 'none',
        PYTHONPATH: resolve(repositoryRoot, 'src'),
        XDG_CONFIG_HOME: configDirectory,
      },
    });
    await waitForFixture(fixture);
    await sleep(1000);
  });

  afterEach(async () => {
    await stopProcessGroup(fixture);
    fixture = undefined;
    if (configDirectory) {
      await rm(configDirectory, { recursive: true, force: true });
      configDirectory = undefined;
    }
  });

  afterAll(async () => {
    await stopProcessGroup(fluxbox);
    await agent?.destroy();
  });

  it('navigates, reports endpoint feedback, resets scroll and completes setup', async () => {
    await runOnboardingFlow(agent);
  });

  it('keeps signed-out navigation locked after cancelling sign-in and allows retry', async () => {
    await cancelAndRetrySignIn(agent);
  });

  it('preserves sign-in when navigating back and resets the account scroll position', async () => {
    await revisitAccount(agent);
  });

  it('blocks continuation with a disabled trigger and preserves a replacement preset', async () => {
    await requireEnabledTrigger(agent);
  });

  it('hides and restores polishing controls without losing the model', async () => {
    await togglePolishing(agent);
  });

  it('shows endpoint failure and recovers after correcting the model', async () => {
    await retryFailedEndpoint(agent);
  });
});
