"""Install verified official archived runtime in this task's disposable guest only."""
import pathlib,json,urllib.request,hashlib,base64,subprocess,re,os
assert os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('ACCEPTANCE_DISPOSABLE_CI')=='1'
root=pathlib.Path('work/runtime');root.mkdir(parents=True,exist_ok=True)
out=pathlib.Path('review-artifacts/versions');out.mkdir(parents=True,exist_ok=True)
pins=json.loads(pathlib.Path('ci/runtime-pins.json').read_text());records=[]
for pkg in pins['packages']:
    filename=pkg['FILENAME'];assert '/' not in filename and filename.endswith('.pkg.tar.zst')
    url='https://archive.archlinux.org/repos/2026/10/01/extra/os/x86_64/'+filename
    target=root/filename
    with urllib.request.urlopen(url,timeout=120) as response, target.open('wb') as dest:
        while block:=response.read(1024*1024): dest.write(block)
    digest=hashlib.sha256(target.read_bytes()).hexdigest();assert digest==pkg['SHA256SUM'],filename
    pathlib.Path(str(target)+'.sig').write_bytes(base64.b64decode(pkg['PGPSIG']))
    records.append({'name':pkg['NAME'],'version':pkg['VERSION'],'source':url,'sha256':digest})
(out/'matched-runtime-packages.json').write_text(json.dumps(records,indent=2))
key=pathlib.Path('work/session-state').read_text().splitlines()[0]
options=['-i',key,'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-o','LogLevel=ERROR']
ssh=['ssh',*options,'-p','2222','omarchy@127.0.0.1']
subprocess.run(ssh+['mkdir -p /tmp/pr13930/runtime'],check=True)
(root/'pacman.conf').write_text('[options]\nArchitecture = auto\nSigLevel = Required DatabaseOptional\nLocalFileSigLevel = Required\n')
(root/'install.sh').write_text('''#!/bin/bash
set -euo pipefail
cd /tmp/pr13930/runtime
for package in *.pkg.tar.zst; do pacman-key --verify "$package.sig"; done
pacman --config /tmp/pr13930/runtime/pacman.conf -U --noconfirm ./*.pkg.tar.zst
pacman -Q qt6-base qt6-declarative qt6-wayland quickshell
quickshell --version
''')
subprocess.run(['scp',*options,'-P','2222',*[str(p) for p in root.iterdir()],'omarchy@127.0.0.1:/tmp/pr13930/runtime/'],check=True)
subprocess.run(['bash','ci/guest.sh','stop'],check=True)
# Existing official disposable harness account only; never expose it in evidence.
password=re.search(r'^GUEST_PASSWORD="([^"\n]+)"',pathlib.Path('work/iso/bin/omarchy-iso-test').read_text(),re.M).group(1)
p=subprocess.run(ssh+['sudo -S bash /tmp/pr13930/runtime/install.sh'],input=password+'\n',text=True,capture_output=True,timeout=300)
(out/'matched-runtime-install.log').write_text(p.stdout+p.stderr)
if p.returncode: raise SystemExit('Verified archive runtime installation failed; original error retained')
p=subprocess.run(['bash','ci/guest.sh','runtime-state'],capture_output=True,text=True,check=True)
state=json.loads(p.stdout);assert state['dropdown']==hashlib.sha256(pathlib.Path('work/expected-head.qml').read_bytes()).hexdigest()
installed=dict(line.split(' ',1) for line in state['packages'].splitlines())
for package in pins['packages']:assert installed[package['NAME']]==package['VERSION'],package['NAME']
print('Installed exact signed Qt 6.11.2 / Quickshell 0.3.1 runtime; pinned product bytes unchanged.')
