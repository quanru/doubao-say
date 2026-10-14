"""Fixed, no-model guest comparison; preserve all frames metadata and first pixels."""
import subprocess,json,pathlib,statistics,base64,time
from PIL import Image
out=pathlib.Path('review-artifacts/versions');results=[]
for index,mode in enumerate(['native-source','native-region','native-region','native-source','native-source','native-region']):
 raw=subprocess.run(['timeout','3','bash','ci/guest.sh',mode],capture_output=True,text=True)
 assert raw.returncode==124,'Premature capture EOF'
 frames=[]
 for line in raw.stdout.splitlines():
  try:x=json.loads(line)
  except json.JSONDecodeError:continue
  png=base64.b64decode(x.pop('pngBase64'))
  if not frames:(out/f'roi-ab-{index}-{mode}.png').write_bytes(png)
  assert x['width']==1280 and x['height']==(28 if mode=='native-region' else 800)
  assert x['frameId'].rsplit('-',1)[1]==str(len(frames)+1)
  frames.append(x)
 assert len(frames)>=20
 (out/f'roi-ab-{index}-{mode}.json').write_text(json.dumps(frames,indent=2))
 for _ in range(30):
  remaining=json.loads(subprocess.check_output(['bash','ci/guest.sh','native-status'],text=True))['capture_pids']
  if not remaining:break
  time.sleep(.1)
 assert not remaining,'Producer survived stop'
 f=frames[2:];gaps=[b['timing']['startMs']-a['timing']['startMs'] for a,b in zip(f,f[1:])]
 encode=[(int(x['pngEncodedNs'])-int(x['readyNs']))/1e6 for x in f]
 results.append({'block':index,'mode':mode,'frames':len(frames),'median_gap_ms':statistics.median(gaps),'max_gap_ms':max(gaps),'median_encode_ms':statistics.median(encode),'remainingCapturePids':remaining})
# State did not change; independently verify full vs native-region label pixels.
labels=[]
for x in results:
 with Image.open(out/f"roi-ab-{x['block']}-{x['mode']}.png") as im:labels.append(im.convert('RGB').crop((1137,0,1173,26)).tobytes())
assert len(set(labels))==1,'Full/ROI label pixels differ; do not proceed'
med=lambda mode:statistics.median(x['median_gap_ms'] for x in results if x['mode']==mode)
summary={'blocks':results,'full_median_ms':med('native-source'),'roi_median_ms':med('native-region'),'ratio':med('native-region')/med('native-source'),'previous_full_median_ms':30.255190,'label_pixels_identical':True,'first_two_frames_excluded_only_from_AB_statistics':True,'no_inference':True}
(out/'roi-ab-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
assert summary['ratio']<.8 and summary['roi_median_ms']<30.255190*.8,'No substantial ROI benefit; stop before trials'
