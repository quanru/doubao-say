import pathlib,subprocess,re,time
state=pathlib.Path('work/session-state').read_text().splitlines();key=state[0]
opts=['-i',key,'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-o','LogLevel=ERROR']
subprocess.run(['scp',*opts,'-P','2222','ci/input-probe.py','omarchy@127.0.0.1:/tmp/pr13930/'],check=True)
password=re.search(r'^GUEST_PASSWORD="([^"\n]+)"',pathlib.Path('work/iso/bin/omarchy-iso-test').read_text(),re.M).group(1)
cmd="sudo -S sh -c 'nohup timeout 810 python3 /tmp/pr13930/input-probe.py </dev/null >/tmp/pr13930/evidence/input-probe.log 2>&1 &'"
subprocess.run(['ssh',*opts,'-p','2222','omarchy@127.0.0.1',cmd],input=password+'\n',text=True,capture_output=True,check=True)
for _ in range(40):
    p=subprocess.run(['bash','ci/guest.sh','probe','start'],capture_output=True)
    if p.returncode==0:break
    time.sleep(.1)
else:raise RuntimeError('Guest input probe did not become ready')
