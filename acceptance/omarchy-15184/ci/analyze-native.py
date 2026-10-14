"""Compare full native source records, never the AI evidence subset. No model calls."""
import pathlib,json,hashlib,statistics,csv,sys
from PIL import Image
out=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'review-artifacts');guest=out/'templates';roi=json.loads((out/'roi.json').read_text())['box']
def pixels(p,full=False):
 with Image.open(p) as im:
  if full:
   assert im.size in [(1280,800),(1280,28)],'Native desktop geometry changed'
   x,y,w,h=roi;im=im.crop((x,y,x+w,y+h))
  return hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
def classify(lo,hi):return 'PASS' if 0<=hi<=500 else 'FAIL' if lo>500 else 'INCONCLUSIVE'
results=[];active=pixels(guest/'active.png');inactive=pixels(guest/'inactive.png');assert active!=inactive
for prefix in ['switch','quick']:
 for i in range(20):
  trial=f'{prefix}{i:02}';directory=out/'observations'/trial
  try:
   record=json.loads((directory/'observation.json').read_text());frames=record['frames'];events=record['events']
   assert record['captureMode']=='source' and record['droppedFrames']==0,'Missing source coverage or buffer overflow'
   down=[e['timing'] for e in events if e['name']=='keydown'];up=[e['timing'] for e in events if e['name']=='keyup']
   assert len(down)==len(up)==1 and down[0]['endMs']<up[0]['startMs'],'Need exactly one monotonic Shift press/release'
   clock=down[0]['clockId'];assert up[0]['clockId']==clock and clock.startswith('linux-monotonic:')
   assert len(frames)>=3 and len(set(f['frameId'] for f in frames))==len(frames),'Missing baseline or duplicate identity'
   previous=-1;old,new=(inactive,active) if i%2==0 else (active,inactive)
   lastold=None;firstnew=None;baseline=False;times=[];unknown=[]
   for index,f in enumerate(frames):
    t=f['timing'];assert t['clockId']==clock and t['kind']=='compositor-frame' and t['startMs']>=previous and t['endMs']>=t['startMs'],'Invalid clock or frame order'
    previous=t['startMs'];times.append(previous)
    if record.get('measurementChannel')=='native-region':
     assert f['geometry']=={'outputIndex':0,'x':0,'y':0,'width':1280,'height':28,'scale':1,'outputWidth':1280,'outputHeight':800,'transform':0},'Region geometry changed'
     assert f['frameId'].rsplit('-',1)[1]==str(index+1),'Missing region sequence'
    h=pixels(directory/f['path'],True)
    if h not in [old,new]:unknown.append(index)
    if t['endMs']<down[0]['startMs']:
     assert h==old,'Target/unknown state before input';baseline=True
    elif h==new and firstnew is None:firstnew=f
    if h==old:
     assert firstnew is None,'Old state returned after target';lastold=f
   assert baseline and lastold and firstnew,'Missing pre-input baseline or transition'
   # Unknown/intermediate pixels cannot establish a stable old/new transition.
   assert not unknown,f'Unknown ROI pixels at {unknown[:5]}'
   triggers={'full_keypress':{'startMs':down[0]['startMs'],'endMs':up[0]['endMs']},'keydown':down[0],'keyup':up[0]}
   metrics={}
   for name,t in triggers.items():
    lo=max(0,lastold['timing']['startMs']-t['endMs']);hi=firstnew['timing']['endMs']-t['startMs']
    metrics[name]={'lower_ms':lo,'upper_ms':hi,'status':classify(lo,hi)}
   gaps=[b-a for a,b in zip(times,times[1:])]
   results.append({'trial':trial,'status':metrics['keydown']['status'],'metrics':metrics,'input_hold_ms':up[0]['startMs']-down[0]['startMs'],'requested_hold_ms':record['requestedHoldMs'],'frame_count':len(frames),'max_gap_ms':max(gaps),'median_gap_ms':statistics.median(gaps),'old_frame':lastold,'new_frame':firstnew,'clockId':clock,'evidence':str(directory.relative_to(out)/'observation.json'),'limit':'compositor frame timing, not physical presentation; fixed candidate acceptance requires keydown upper bound <=500ms; full-keypress and keyup are retained separately'})
  except (OSError,KeyError,AssertionError,ValueError) as error:results.append({'trial':trial,'status':'INCONCLUSIVE','reason':str(error)})
(out/'latency-results.json').write_text(json.dumps(results,indent=2))
with (out/'latency.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['trial','metric','lower_ms','upper_ms','status','max_gap_ms','evidence'])
 for r in results:
  for name,m in r.get('metrics',{}).items():w.writerow([r['trial'],name,m['lower_ms'],m['upper_ms'],m['status'],r['max_gap_ms'],r['evidence']])
print(json.dumps({prefix:{s:sum(r['trial'].startswith(prefix) and r['status']==s for r in results) for s in ['PASS','FAIL','INCONCLUSIVE']} for prefix in ['switch','quick']}))
# Fixed candidate gate: all predeclared keydown upper bounds must be <=500ms.
if any(r['status']!='PASS' for r in results):sys.exit(1)
