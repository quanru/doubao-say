"""Require a visible app window and a live process before stopping our own app."""
import os
import subprocess
import sys
import tempfile
import time


def main():
    command = sys.argv[1:]
    if command[:1] == ['--']:
        command = command[1:]
    env = {**os.environ, 'XDG_SESSION_TYPE': 'x11'}
    env.pop('WAYLAND_DISPLAY', None)
    env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
    with tempfile.TemporaryFile(mode='w+') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and process.poll() is None:
                windows = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', 'Doubao Say'],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                if windows.returncode == 0 and windows.stdout.strip():
                    print('PASS: live application and visible Doubao Say window')
                    return
                time.sleep(0.5)
            log.seek(0)
            raise SystemExit('Application launch failed:\n' + log.read())
        finally:
            import signal
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == '__main__':
    main()
