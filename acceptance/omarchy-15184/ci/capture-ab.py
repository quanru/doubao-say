"""Bounded pre-inference full-frame A/B; no input injection or outcome selection."""
import subprocess,json,pathlib,statistics
from decimal import Decimal as D
out=pathlib.Path('review-artifacts/versions');results=[]
for index,mode in enumerate(['adaptive','none','none','adaptive','adaptive','none']):
 raw=subprocess.run(['timeout','3','bash','ci/guest.sh','native-source',mode],capture_output=True,text=True)
 assert raw.returncode==124, 'Capture ended before A/B timeout'
 frames=[]
 for line in raw.stdout.splitlines():
  try:x=json.loads(line)
  except json.JSONDecodeError:continue
  x.pop('pngBase64',None);frames.append(x)
 assert len(frames)>=20 and all(x['width']==1280 and x['height']==800 for x in frames)
 (out/f'capture-ab-{index}-{mode}.json').write_text(json.dumps(frames,indent=2))
 subprocess.run(['bash','ci/guest.sh','native-status'],check=True,capture_output=True)
 # Exclude only the documented first-frame startup for the controlled comparison.
 f=frames[2:];gaps=[b['timing']['startMs']-a['timing']['startMs'] for a,b in zip(f,f[1:])]
 encode=[(int(x['pngEncodedNs'])-int(x['readyNs']))/1e6 for x in f]
 results.append({'block':index,'filter':mode,'frames':len(frames),'median_gap_ms':statistics.median(gaps),'max_gap_ms':max(gaps),'median_encode_ms':statistics.median(encode)})
 # Timeout closes SSH; verify the actual guest producer is gone before the next block.
 import time
 for _ in range(30):
  remaining=json.loads(subprocess.check_output(['bash','ci/guest.sh','native-status'],text=True))['capture_pids']
  if not remaining:break
  time.sleep(.1)
 assert not remaining,'A/B producer survived stop'
med=lambda mode,key:statistics.median(x[key] for x in results if x['filter']==mode)
summary={'blocks':results,'default_filter':'none','median_gap_ratio':med('none','median_gap_ms')/med('adaptive','median_gap_ms'),'median_encode_ratio':med('none','median_encode_ms')/med('adaptive','median_encode_ms'),'limit':'Observed A/B medians, not a universal latency or sampling guarantee'}
(out/'capture-ab-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
assert summary['median_encode_ratio']<.75 and summary['median_gap_ratio']<.9,'No demonstrated capture benefit; stop before inference'
