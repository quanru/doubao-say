"""Evaluate genuine guest captures. Unknown pixels/threshold overlap => inconclusive."""
import pathlib,json,csv,hashlib,sys
from PIL import Image
root=pathlib.Path('review-artifacts/guest');out=pathlib.Path('review-artifacts')
def pixels(p):
 with Image.open(p) as im:
  if im.size==(1280,28):
   x,y,w,h=json.loads((out/'roi.json').read_text())['box'];im=im.crop((x,y,x+w,y+h))
  return hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
results=[];rows=[]
try:
 active=pixels(root/'active.png');inactive=pixels(root/'inactive.png')
 if active==inactive:raise ValueError('ROI templates are identical; invalid localization')
 for i in range(20):
  trial=f'switch{i:02}';d=root/trial;capture=json.loads((d/'capture.json').read_text())
  events=sorted({(e['ns'],e['value']) for e in capture['events']})
  down=[t for t,v in events if v==1];up=[t for t,v in events if v==0]
  if len(down)!=1 or len(up)!=1 or down[0]>=up[0]:raise ValueError(f'{trial}: need exactly one Shift down/up pair')
  a,b=down[0]-1000,up[0]+1000
  target,old=(active,inactive) if i%2==0 else (inactive,active)
  frames=capture['frames'];lastold=None;firstnew=None;preold=False
  for f in frames:
   h=pixels(d/f['file'])
   if f['hi_ns']<a:
    if h==old:preold=True;lastold=f
    continue
   if h==old and firstnew is None:lastold=f
   if h==target and firstnew is None:firstnew=f
  if not preold or lastold is None or firstnew is None:
   results.append({'trial':trial,'status':'INCONCLUSIVE','reason':'Missing pre-input old state, old/new boundary or target pixels'});continue
  lo=max(0,lastold['lo_ns']-b)/1e6;hi=(firstnew['hi_ns']-a)/1e6
  status='PASS' if 0<=hi<=500 else 'FAIL' if lo>500 else 'INCONCLUSIVE'
  record={'trial':trial,'status':status,'lower_ms':lo,'upper_ms':hi,'old_frame':lastold['file'],'new_frame':firstnew['file'],'review_required':True,'assumption':'monotonic stable label transition; grim brackets bound capture; no physical-monitor latency measured'}
  results.append(record);rows.append([trial,a,b,lastold['lo_ns'],firstnew['hi_ns'],f'guest/{trial}/capture.json'])
except (OSError,ValueError,KeyError) as e:
 results.append({'status':'NOT_EXECUTED_OR_INCONCLUSIVE','reason':str(e)})
with (out/'latency.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['trial','input_lo_ns','input_hi_ns','visible_lo_ns','visible_hi_ns','evidence']);w.writerows(rows)
(out/'latency-results.json').write_text(json.dumps(results,indent=2))
if len(rows)!=20 or any(r['status']!='PASS' for r in results):sys.exit(1)
