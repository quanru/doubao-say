"""Synthetic arithmetic/pixel tests in temp dirs, explicitly not acceptance evidence."""
from pathlib import Path
from PIL import Image
import tempfile,json,subprocess,sys,shutil
script=Path(__file__).with_name('analyze-captures.py').resolve()
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'review-artifacts/guest';root.mkdir(parents=True)
 for name,color in [('active','red'),('inactive','blue')]:Image.new('RGB',(8,8),color).save(root/(name+'.png'))
 for i in range(20):
  d=root/f'switch{i:02}';d.mkdir();target,old=('active','inactive') if i%2==0 else ('inactive','active')
  rows=[]
  for j,(state,lo,hi) in enumerate([(old,800000000,850000000),(old,1100000000,1120000000),(target,1400000000,1420000000)]):
   name=f'{j:04}.png';shutil.copy(root/(state+'.png'),d/name);rows.append({'file':name,'lo_ns':lo,'hi_ns':hi})
  data={'events':[{'ns':1000000000,'value':1},{'ns':1080000000,'value':0}],'frames':rows};(d/'capture.json').write_text(json.dumps(data))
 p=subprocess.run([sys.executable,str(script)],cwd=tmp);assert p.returncode==0
 rows=json.loads((Path(tmp)/'review-artifacts/latency-results.json').read_text());assert len(rows)==20 and all(x['status']=='PASS' for x in rows)
 d=root/'switch00/capture.json';data=json.loads(d.read_text());data['frames'][1].update(lo_ns=1600000000,hi_ns=1620000000);data['frames'][2].update(lo_ns=1650000000,hi_ns=1670000000);d.write_text(json.dumps(data))
 p=subprocess.run([sys.executable,str(script)],cwd=tmp);assert p.returncode==1
 rows=json.loads((Path(tmp)/'review-artifacts/latency-results.json').read_text());assert rows[0]['status']=='FAIL'
print('PASS: synthetic pixel/interval test covers 20 sample success and >500ms failure; no real desktop or model used.')
