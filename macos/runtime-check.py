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
    if '--settings' in sys.argv[3:]:
        cases += [(f'settings-{tab}', '--settings-smoke-test', tab) for tab in ['setup', 'recognition', 'polishing', 'shortcuts', 'general', 'result']]
    for label, argument, tab in cases:
        env = dict(os.environ, DOUBAO_SMOKE_IMAGE=str(output / f'{label}-{language}.png'), DOUBAO_SMOKE_TAB=tab)
        command = [str(bundle / 'Contents/MacOS/DoubaoSay'), argument, '-language', language]
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
