"""Harness-only tests with synthetic data/loopback transport; no real acceptance claims."""
from pathlib import Path
import subprocess,sys,tempfile,socket,time,json,urllib.request,urllib.error,shutil
root=Path(__file__).resolve().parents[1]
# Exercise request cap including failures, with a closed loopback port (no provider).
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
p=subprocess.Popen([sys.executable,str(root/'scripts/budget-gate.py'),'--upstream','https://127.0.0.1:1','--model','local-test','--approved-model-use','--max-requests','2','--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(100):
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.1):break
  except OSError:time.sleep(.02)
 statuses=[]
 for _ in range(3):
  req=urllib.request.Request(f'http://127.0.0.1:{port}/chat/completions',data=json.dumps({'model':'local-test','messages':[]}).encode(),headers={'Content-Type':'application/json'})
  try:statuses.append(urllib.request.urlopen(req,timeout=3).status)
  except urllib.error.HTTPError as e:statuses.append(e.code)
 assert statuses==[502,502,429],statuses
finally:p.terminate();p.wait(timeout=5)
# Patch the pinned harness in a throwaway directory and validate generated shell.
with tempfile.TemporaryDirectory() as d:
 target=Path(d)/'work/iso/bin';target.mkdir(parents=True)
 harness=root/'omarchy-iso/bin/omarchy-iso-test'
 if not harness.exists():harness=root/'work/iso/bin/omarchy-iso-test'
 if not harness.exists():raise SystemExit('Provide pinned ISO source for patch test; cap test passed')
 shutil.copy(harness,target/'omarchy-iso-test')
 subprocess.run([sys.executable,str(root/'ci/patch-harness.py')],cwd=d,check=True)
 subprocess.run(['bash','-n',str(target/'acceptance-session')],check=True)
print('PASS: request cap counts failed upstream attempts and blocks third request; generated pinned harness passes bash -n. No VM or model used.')
