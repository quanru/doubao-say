"""No outcome threshold gate: validate semantics and disclose measured disturbance."""
from pathlib import Path
from PIL import Image
import json,hashlib,statistics,re
r=Path('review-artifacts/presentation-preflight');issues=[];result={'modes':{},'issues':issues}
def rgb(p):
 with Image.open(p) as im:
  if im.size==(1280,28):im=im.crop((1137,0,1173,26))
  assert im.size==(36,26)
  if im.mode=='RGBA':assert im.getextrema()[3]==(255,255),'Nonopaque GL ROI needs explicit compositor blending model'
  return hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
try:
 for mode in ['discovery','plain','passive','feedback','pixels']:
  rows=[];native_hashes=set();window_start=None;window_end=None
  for i in range(4):
   d=r/mode/str(i);rec=json.loads((d/'record.json').read_text());fs=rec['frames'];events=rec['input']['events'];assert len([e for e in events if e['value']==1])==len([e for e in events if e['value']==0])==1
   if window_start is None:window_start=fs[0]['timing']['startMs']*1e6
   window_end=fs[-1]['timing']['endMs']*1e6
   down=next(e['ns'] for e in events if e['value']==1);up=next(e['ns'] for e in events if e['value']==0)
   hashes=[rgb(d/f['path']) for f in fs];native_hashes.update(hashes);assert len(set(hashes))==2,'Need two actual stable label states'
   first=next(n for n,h in enumerate(hashes) if h!=hashes[0]);assert all(h==hashes[first] for h in hashes[first:]),'Unexpected intermediate pixels'
   old,new=fs[first-1],fs[first];lo=max(0,old['timing']['startMs']-up/1e6);hi=new['timing']['endMs']-down/1e6
   rows.append({'trial':i,'full_keypress_lower_ms':lo,'full_keypress_upper_ms':hi,'frame_count':len(fs),'clockId':rec['input']['clockId']})
  result['modes'][mode]={'trials':rows,'native_label_states':len(native_hashes)}
  if mode in ['feedback','pixels','passive']:
   events=[json.loads(x) for x in (r/mode/'events.jsonl').read_text().splitlines() if x.startswith('{')]
   assert not [x for x in events if x['event']=='fatal'],events
   starts=[x for x in events if x['event']=='start'];assert len(starts)==1 and starts[0]['clockId']==rows[0]['clockId'],'Unexpected observer process or clock'
   all_swaps={x['token']:x for x in events if x['event']=='swap-begin'};swaps={t:x for t,x in all_swaps.items() if window_start<=int(x['enterNs'])<=window_end};ends={x['token']:x for x in events if x['event']=='swap-end'};present={x['token']:x for x in events if x['event']=='presented'}
   assert swaps and len({x['surface'] for x in swaps.values()})==1,'Not a unique bar surface'
   assert all(t in ends and ends[t]['ok'] for t in swaps),'Missing/failed EGL swap'
   result['modes'][mode].update(swaps=len(swaps),presented=len(present),surface=next(iter(swaps.values()))['surface'],observer_before_swap_ms=[(int(x['beforeSwapNs'])-int(x['enterNs']))/1e6 for x in swaps.values()])
   if mode=='feedback':
    protocol=json.loads((r/mode/'protocol.json').read_text())['lines'];pending_surface={};pairs=0
    for line in protocol:
     request=re.search(r'wp_presentation[#@]\d+\.feedback\(wl_surface[#@](\d+),',line)
     commit=re.search(r'wl_surface[#@](\d+)\.commit\(',line)
     if request:pending_surface[request[1]]=pending_surface.get(request[1],0)+1
     if commit and pending_surface.get(commit[1],0):pairs+=pending_surface.pop(commit[1])
    assert pairs>=len(swaps),'Protocol trace does not establish feedback→same-surface commit association'
    result['modes'][mode]['feedback_followed_by_surface_commit']=pairs
   if mode!='passive':
    assert any(x['event']=='presentation-clock' and x['monotonic'] for x in events)
    assert set(swaps)<=set(present),'Missing or discarded presentation feedback in measured windows'
    for token,x in present.items():
     if token not in swaps:continue
     assert int(swaps[token]['beforeSwapNs'])<=int(x['sourceNs'])<=int(x['receiptNs'])
    result['modes'][mode]['presentation_flags']=sorted(set(x['flags'] for x in present.values()))
   if mode=='pixels':
    reads=[];matched=0
    for token,x in swaps.items():
     assert x['pixelSaved'],'GL evidence unavailable'
     h=rgb(r/mode/f'pixel-{token}.png')
     assert h in native_hashes,'GL pixels do not match compositor label states'
     matched+=1
     # Startup paints may predate the measured input state; keep but do not interpret them.
     reads.append((int(x['readEndNs'])-int(x['readStartNs']))/1e6)
    assert matched>=4,'GL pixels do not match genuine compositor label states'
    result['modes'][mode].update(matched_pixel_feedbacks=matched,readback_ms=reads)
 result['semantic_validation']='PASSED'
except Exception as error:
 issues.append(str(error));result['semantic_validation']='FAILED'
result['limit']='Small fixed mode comparison quantifies observer cost; not a statistical equivalence claim. New feedback was injected by the observer on the owning connection. All source intervals retained; no percentage-performance gate.'
Path('review-artifacts/versions/presentation-preflight.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if issues:raise SystemExit(1)
