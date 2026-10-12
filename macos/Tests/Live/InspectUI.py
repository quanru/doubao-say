"""Opt-in native UI inspection; isolated bundle, synthetic state, bounded process."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import uuid

source = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
output.mkdir(parents=True, exist_ok=True)
bundle = output / 'Doubao Say Inspect.app'
subprocess.run(['ditto', str(source), str(bundle)], check=True)
info_path = bundle / 'Contents/Info.plist'
info = plistlib.loads(info_path.read_bytes())
info['CFBundleIdentifier'] = 'md.lifeos.doubao-say.inspect.' + uuid.uuid4().hex
info_path.write_bytes(plistlib.dumps(info))
subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
hold = min(max(int(sys.argv[4]) if len(sys.argv) > 4 else 120, 2), 120)
mode = sys.argv[5] if len(sys.argv) > 5 else 'polishing'
env = dict(os.environ, DOUBAO_SMOKE_HOLD_SECONDS=str(hold), DOUBAO_SMOKE_TAB=mode)
argument = '--smoke-test' if mode == 'overlay' else '--settings-smoke-test'
process = subprocess.Popen([str(bundle / 'Contents/MacOS/DoubaoSay'), argument, '-language', sys.argv[3]], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    logs, _ = process.communicate(timeout=hold + 10)
    (output / 'inspect.log').write_text(logs)
    raise SystemExit(process.returncode)
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
