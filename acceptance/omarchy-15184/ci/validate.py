"""Offline static checks only. Does not boot a VM or invoke a model."""
from pathlib import Path
import ast,json,subprocess,re
r=Path('.')
for p in [*(r/'ci').glob('*.py'),*(r/'scripts').glob('*.py')]:ast.parse(p.read_text())
for p in (r/'ci').glob('*.sh'):subprocess.run(['bash','-n',str(p)],check=True)
subprocess.run(['node','--check','ci/ui.mjs'],check=True)
subprocess.run(['node','--check','ci/native-smoke.mjs'],check=True)
pins=json.loads((r/'ci/pins.json').read_text())
for k in ['omarchy','base_tip','iso','pkgs','reference']:assert re.fullmatch('[a-f0-9]{40}',pins[k])
lock=json.loads((r/'ci/package-lock.json').read_text());assert lock['packages']['']['dependencies']['@midscene/computer']=='1.15.3'
workflow=(r/'ci/workflow.yml').read_text()
assert 'pages: write' not in workflow and 'deploy-midscene' not in workflow
assert 'paths: [acceptance/omarchy-15184/ci/.run-acceptance]' in workflow and '\n  pull_request:' not in workflow
assert 'max-parallel:' not in workflow
assert "MIDSCENE_MODEL_STREAM_MODE: 'non-stream'" in workflow
assert 'MIDSCENE_MODEL_API_KEY' not in (r/'ci/prepare-runner.sh').read_text()
assert 'wtype' not in (r/'ci/ui.mjs').read_text()
assert 'SetInputMethodGroupInfo' not in (r/'ci/guest.py').read_text()
assert 'work/session-state' not in workflow
print('PASS: Python/Bash/JS syntax, source pins, lockfile, manual or exact-marker trigger, no Pages, credential-stage separation, QMP-only switching, no controller list setters.')
