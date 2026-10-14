"""Synthetic unit fixtures only; never included as real acceptance evidence."""
import tempfile,pathlib,json,subprocess,sys
from PIL import Image
script=pathlib.Path(__file__).with_name('analyze-native.py').resolve()
with tempfile.TemporaryDirectory() as tmp:
 r=pathlib.Path(tmp)/'review-artifacts';(r/'templates').mkdir(parents=True);(r/'roi.json').write_text(json.dumps({'box':[0,0,4,4]}))
 for name,color in [('active','red'),('inactive','blue')]:Image.new('RGB',(4,4),color).save(r/'templates'/f'{name}.png')
 def t(ms,kind='compositor-frame'):return {'clockId':'linux-monotonic:unit-fixture','kind':kind,'startMs':ms,'endMs':ms}
 for prefix in ['switch','quick']:
  for i in range(20):
   d=r/'observations'/f'{prefix}{i:02}';d.mkdir(parents=True)
   Image.new('RGB',(1280,800),'blue' if i%2==0 else 'red').save(d/'old.png')
   Image.new('RGB',(1280,800),'red' if i%2==0 else 'blue').save(d/'new.png')
   oldms,newms=(1490,1500) if i==0 else (1500.001,1520) if i==1 else (1440,1560)
   frames=[{'frameId':str(j),'path':path,'timing':t(ms)} for j,(path,ms) in enumerate([('old.png',950),('old.png',oldms),('new.png',newms)])]
   (d/'observation.json').write_text(json.dumps({'frames':frames,'events':[{'name':'keydown','timing':t(1000,'input-event')},{'name':'keyup','timing':t(1001,'input-event')}],'captureMode':'source','droppedFrames':0,'requestedHoldMs':1}))
 p=subprocess.run([sys.executable,str(script)],cwd=tmp,capture_output=True,text=True);assert p.returncode==1,p.stderr
 data=json.loads((r/'latency-results.json').read_text());assert data[0]['status']=='PASS';assert data[1]['status']=='FAIL';assert data[1]['metrics']['keydown']['status']=='FAIL';assert data[2]['status']=='INCONCLUSIVE';assert data[2]['max_gap_ms']==490
 print('PASS: native full-record analysis preserves inclusive threshold, real failure, crossing interval and actual gaps. Synthetic unit data only.')
