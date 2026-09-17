import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { type ComputerAgent, agentFromComputer } from '@midscene/computer';
import { afterAll, beforeAll, describe, it } from '@rstest/core';

const sleep = (milliseconds: number) =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

const stopProcessGroup = (child?: ChildProcess) => {
  if (!child?.pid) return;
  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch {
    // The process may already have exited after a test failure.
  }
};

const guest = (command: string) => {
  const key = process.env.OMARCHY_SSH_KEY;
  if (!key) throw new Error('OMARCHY_SSH_KEY is required for the Omarchy E2E');
  const sessionEnvironment = [
    'export XDG_RUNTIME_DIR=/run/user/$(id -u);',
    'export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus;',
    'export HYPRLAND_INSTANCE_SIGNATURE=$(ls -t "$XDG_RUNTIME_DIR/hypr" | head -1);',
    'export WAYLAND_DISPLAY=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -name "wayland-*" ! -name "*.lock" -printf "%f\\n" | head -1);',
    'export OMARCHY_PATH=/usr/share/omarchy;',
    'export PATH="$OMARCHY_PATH/bin:$PATH";',
  ].join(' ');

  return execFileSync(
    'ssh',
    [
      '-i',
      key,
      '-p',
      '2222',
      '-o',
      'BatchMode=yes',
      '-o',
      'IdentitiesOnly=yes',
      '-o',
      'StrictHostKeyChecking=no',
      '-o',
      'UserKnownHostsFile=/dev/null',
      '-o',
      'ConnectTimeout=10',
      '-o',
      'LogLevel=ERROR',
      'omarchy@127.0.0.1',
      `${sessionEnvironment} ${command}`,
    ],
    { encoding: 'utf8', timeout: 20_000 },
  ).trim();
};

describe.skipIf(process.env.OMARCHY_E2E !== 'true')(
  'Omarchy shell visuals in a real Hyprland session',
  () => {
    let agent: ComputerAgent;
    let fluxbox: ChildProcess;
    let viewer: ChildProcess;
    let barConfigBackup: string | undefined;
    let barConfigExisted = false;

    beforeAll(async () => {
      agent = await agentFromComputer({
        aiContexts: {
          aiAssert:
            'Inspect the real Omarchy desktop shown through VNC. ' +
            'Judge only visible pixels. Do not infer success from an action or a configuration value.',
        },
        // TigerVNC must show the guest framebuffer without scaling or borders.
        xvfbResolution: '1280x800x24',
      });

      fluxbox = spawn('fluxbox', [], {
        detached: true,
        stdio: 'ignore',
        env: process.env,
      });
      await sleep(1000);
      viewer = spawn(
        'vncviewer',
        ['-FullScreen=1', '-RemoteResize=0', '-ViewOnly=0', '127.0.0.1:5905'],
        { detached: true, stdio: 'ignore', env: process.env },
      );
      await sleep(4000);
    });

    afterAll(() => {
      if (barConfigBackup) {
        try {
          guest(
            `${barConfigExisted ? `cp '${barConfigBackup}' "$HOME/.config/omarchy/shell.json"` : 'rm -f "$HOME/.config/omarchy/shell.json"'}; ` +
              `omarchy-shell shell reloadConfig; rm -f '${barConfigBackup}'`,
          );
        } catch (error) {
          console.error(
            'Could not restore the Omarchy bar configuration:',
            error,
          );
        }
      }
      try {
        guest('omarchy-shell shell hide omarchy.menu');
      } catch {
        // The disposable VM may already have stopped.
      }
      stopProcessGroup(viewer);
      stopProcessGroup(fluxbox);
    });

    it('shows the system menu with Shutdown and a visible focused row', async () => {
      guest('omarchy-shell shell summon omarchy.menu \'{"menu":"system"}\'');
      let menuVisible = false;
      for (let attempt = 0; attempt < 15; attempt++) {
        if (
          guest(
            'hyprctl -j layers | jq -r \'[.. | objects | select(.namespace? == "omarchy-menu")] | length\'',
          ) !== '0'
        ) {
          menuVisible = true;
          break;
        }
        await sleep(1000);
      }
      if (!menuVisible) throw new Error('Omarchy system menu did not open');
      guest('wtype -k Down');
      await sleep(1000);

      await agent.aiAssert(
        'The Omarchy system menu is open, and its Shutdown item is clearly readable.',
      );
      await agent.aiAssert(
        'Exactly one row in the open system menu has a visible focus highlight or accent, and the highlight is rendered cleanly.',
      );
      guest('omarchy-shell shell hide omarchy.menu');
    });

    it('renders the bar vertically along the left screen edge', async () => {
      barConfigExisted =
        guest(
          'test -f "$HOME/.config/omarchy/shell.json" && echo yes || echo no',
        ) === 'yes';
      barConfigBackup = guest('mktemp /tmp/omarchy-midscene-bar.XXXXXX');
      if (barConfigExisted) {
        guest(`cp "$HOME/.config/omarchy/shell.json" '${barConfigBackup}'`);
      }
      guest('omarchy bar position left');
      await sleep(2000);

      await agent.aiAssert(
        'The Omarchy bar is visible as a tall vertical bar docked to the left edge of the desktop, rather than a horizontal bar across the top or bottom.',
      );
    });
  },
);
