"""Run an isolated synthetic Mac UI check; no audio, accounts, or paste events."""
import os
import pathlib
import plistlib
import subprocess
import sys
import uuid

source = pathlib.Path(sys.argv[1]).resolve()
output = pathlib.Path(sys.argv[2]).resolve()
output.mkdir(parents=True, exist_ok=True)
bundle = output / 'Doubao Say Verify.app'
subprocess.run(['ditto', str(source), str(bundle)], check=True)
info_path = bundle / 'Contents/Info.plist'
info = plistlib.loads(info_path.read_bytes())
info['CFBundleIdentifier'] = 'md.lifeos.doubao-say.macos.verify.' + uuid.uuid4().hex
info_path.write_bytes(plistlib.dumps(info))
subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
for language in ['en', 'zh']:
    cases = [('overlay', '--smoke-test', '')]
    if '--launch-settings' in sys.argv[3:]:
        cases = [(f'launch-{status}', '--settings-smoke-test', 'general') for status in ['available', 'latest']]
    if '--saved-setup' in sys.argv[3:]:
        cases = [('saved-setup', '--settings-smoke-test', 'setup')]
    if '--setup-completion' in sys.argv[3:]:
        cases = [(f'setup-{status}-{theme}', '--settings-smoke-test', 'setup')
                 for status in ['complete', 'pending'] for theme in ['light', 'dark']]
    if '--doubao-session' in sys.argv[3:]:
        cases = [(f'doubao-{status}', '--settings-smoke-test', 'recognition') for status in ['signed-in', 'signed-out']]
    if '--recent-text' in sys.argv[3:]:
        cases = [(f'recent-text-{length}', '--settings-smoke-test', 'result') for length in ['short', 'long']]
    if '--microphone-menu' in sys.argv[3:]:
        cases = [('microphone-menu', '--settings-smoke-test', 'general')]
    if '--input-failure' in sys.argv[3:]:
        cases = [('input-failure', '--smoke-test', '')]
    if '--settings' in sys.argv[3:]:
        cases += [(f'settings-{tab}', '--settings-smoke-test', tab) for tab in ['setup', 'recognition', 'polishing', 'shortcuts', 'general', 'result']]
    for label, argument, tab in cases:
        env = dict(os.environ, DOUBAO_SMOKE_IMAGE=str(output / f'{label}-{language}.png'), DOUBAO_SMOKE_TAB=tab)
        if label == 'saved-setup':
            env['DOUBAO_SMOKE_ONBOARDING_SAVED'] = '1'
        if label == 'input-failure':
            env['DOUBAO_SMOKE_INPUT_FAILURE'] = '1'
        if label == 'microphone-menu':
            env['DOUBAO_SMOKE_MICROPHONE_MENU'] = '1'
        if label == 'recent-text-long':
            env['DOUBAO_SMOKE_RECENT_LONG'] = '1'
        if '--expect-text-padding' in sys.argv[3:]:
            env['DOUBAO_SMOKE_EXPECT_TEXT_PADDING'] = '1'
        if label.startswith('doubao-'):
            env['DOUBAO_SMOKE_SIGNED_IN'] = '1' if label == 'doubao-signed-in' else '0'
        if label.startswith('launch-'):
            env.update(DOUBAO_SMOKE_LAUNCH_CHECK='1',
                       DOUBAO_SMOKE_UPDATE_VERSION='1.8.2' if label.endswith('available') else '')
        command = [str(bundle / 'Contents/MacOS/DoubaoSay'), argument, '-language', language]
        if label.startswith('setup-') and '--setup-completion' in sys.argv[3:]:
            env.update(DOUBAO_SMOKE_SETUP_STEP='1',
                       DOUBAO_SMOKE_SETUP_COMPLETE='1' if label.startswith('setup-complete-') else '0',
                       DOUBAO_SMOKE_APPEARANCE='dark' if label.endswith('-dark') else 'light')
        lines = []
        capture_path = output / f'{label}-{language}.png'
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        capture_ok = False
        try:
            # The dev-gate runtime deadline bounds this host; each child also has an alarm timer.
            import threading
            expiry = threading.Timer(15, process.kill)
            expiry.start()
            for line in process.stdout:
                lines.append(line)
                if line.startswith('CAPTURE_WINDOW:'):
                    window_id = line.strip().split(':', 1)[1]
                    screenshot = subprocess.run(['/usr/sbin/screencapture', '-x', '-o', '-l', window_id, str(capture_path)], capture_output=True, text=True, timeout=5)
                    capture_ok = screenshot.returncode == 0 and capture_path.is_file()
                    if not capture_ok:
                        lines.append('FAIL: host window capture unavailable\n')
            return_code = process.wait(timeout=2)
        finally:
            expiry.cancel()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        (output / f'{label}-{language}.log').write_text(''.join(lines))
        if return_code or not capture_ok:
            raise SystemExit(return_code or 1)
        print(f'{label} {language}: captured native window; process exited')
