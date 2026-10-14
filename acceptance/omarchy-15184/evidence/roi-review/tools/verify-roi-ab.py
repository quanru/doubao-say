from pathlib import Path
from decimal import Decimal as D
import json,sys,hashlib,statistics
from PIL import Image
r=Path(sys.argv[1]);read=lambda p:json.loads((r/p).read_text(),parse_float=D)
manifest=0
for line in (r/'SHA256SUMS').read_text().splitlines():
 h,name=line.split('  ',1);p=(r/name).resolve();assert p.is_relative_to(r.resolve()) and hashlib.sha256(p.read_bytes()).hexdigest()==h;manifest+=1
trace={}
for line in (r/'guest/native-capture-errors.log').read_text().splitlines():
 if not line.startswith('{'):continue
 x=json.loads(line);key=x['frameId']
 if key in trace:assert all(trace[key].get(k,v)==v for k,v in x.items())
 trace.setdefault(key,{}).update(x)
summary=read('versions/roi-ab-summary.json');blocks=[];labels=[];max_rounding=D(0);frames_total=0
for block,mode in enumerate(['native-source','native-region','native-region','native-source','native-source','native-region']):
 frames=read(f'versions/roi-ab-{block}-{mode}.json');assert len(frames)>=20
 expected={'scope':'region' if mode=='native-region' else 'output','outputIndex':0,'x':0,'y':0,'width':1280,'height':28 if mode=='native-region' else 800,'scale':1,'outputWidth':1280,'outputHeight':800,'transform':0}
 pid=frames[0]['frameId'].rsplit('-',1)[0];clock=frames[0]['timing']['clockId'];assert clock.startswith('linux-monotonic:');times=[];decomp={k:[] for k in ['source_to_ready_ms','encode_ms','output_ms','next_request_ms','next_request_to_source_ms']}
 for i,f in enumerate(frames):
  assert f['frameId']==f'{pid}-{i+1}' and f['geometry']==expected
  assert f['width']==1280 and f['height']==expected['height']
  t=f['timing'];assert t['clockId']==clock and t['kind']=='compositor-frame';a=trace[f['frameId']]
  req,src,ready,enc,emit=[int(a[k]) for k in ['requestedNs','sourceNs','readyNs','encodedNs','emittedNs']];assert req<=src<=ready<=enc<=emit
  assert int(f['captureStartNs'])==req and int(f['readyNs'])==ready and int(f['pngEncodedNs'])==enc
  lo,hi=[D(t[k])*1000000 for k in ['startMs','endMs']];assert lo<=src<=hi and hi-lo==2000
  max_rounding=max(max_rounding,abs((lo+hi)/2-src));times.append(D(src)/1000000)
  if i>=2:
   decomp['source_to_ready_ms'].append((ready-src)/1e6);decomp['encode_ms'].append((enc-ready)/1e6);decomp['output_ms'].append((emit-enc)/1e6)
   if i+1<len(frames):
    nxt=trace[frames[i+1]['frameId']];decomp['next_request_ms'].append((int(nxt['requestedNs'])-emit)/1e6);decomp['next_request_to_source_ms'].append((int(nxt['sourceNs'])-int(nxt['requestedNs']))/1e6)
 f=times[2:];gaps=[b-a for a,b in zip(f,f[1:])];b=summary['blocks'][block]
 assert abs(D(b['median_gap_ms'])-statistics.median(gaps))<D('.000001') and b['remainingCapturePids']==[]
 png=r/f'versions/roi-ab-{block}-{mode}.png';assert png.stat().st_size==trace[frames[0]['frameId']]['pngBytes']
 with Image.open(png) as im:
  assert im.size==(1280,expected['height']);labels.append(im.convert('RGB').crop((1137,0,1173,26)).tobytes())
 blocks.append({'block':block,'mode':mode,'frames':len(frames),'median_gap_ms':str(statistics.median(gaps)),'max_gap_ms':str(max(gaps)),'median_components_ms':{k:statistics.median(v) for k,v in decomp.items()}});frames_total+=len(frames)
assert len(set(labels))==1
clock=read('versions/guest-clock-check.json');assert len(clock['samples'])==10000 and all(int(a)<=int(s)<=int(b) for a,s,b in clock['samples'])
lifecycle=read('versions/native-lifecycle.json');assert len(lifecycle)==3 and all(x['remainingCapturePids']==[] for x in lifecycle)
integrity=read('guest/candidate-integrity.json');assert not integrity['mismatches']
restore=read('guest/restore.json');assert restore['config_byte_identical'] and restore['service_restarted_only_during_cleanup']
identity=lambda s:sorted((p['pid'],p['start_ticks'],p['comm']) for p in s['processes'])
assert identity(read('guest/initial.json'))==identity(read('guest/before-restore.json'))
full=statistics.median(D(b['median_gap_ms']) for b in blocks if b['mode']=='native-source');roi=statistics.median(D(b['median_gap_ms']) for b in blocks if b['mode']=='native-region')
assert not(roi/full<D('.8') and roi<D('30.255190')*D('.8'))
result={'verified_manifest_files':manifest,'verified_ab_frames_metadata':frames_total,'retained_png_count':6,'all_six_label_pixels_identical':True,'candidate_files_verified':integrity['checked_files'],'native_lifecycles':3,'all_ab_cleanup_zero':True,'same_processes_before_restore':True,'restored_byte_identically':True,'clock_samples':10000,'max_numeric_center_error_ns':str(max_rounding),'full_median_ms':str(full),'roi_median_ms':str(roi),'reduction_vs_same_guest_percent':str((1-roi/full)*100),'reduction_vs_prior_percent':str((1-roi/D('30.255190'))*100),'performance_gate':'FAILED_PREDECLARED_20_PERCENT','timing_trials_executed':0,'model_calls':0,'blocks':blocks,'limits':['A/B keeps metadata for every delivered frame but PNG only for the first frame of each block. These are idle performance windows, not input latency trials.','RegionObservation SDK real guest lifecycle and Agent HTML steps were gated off; unit-tested interface not claimed fully exercised in guest.','Source event is not physical presentation; contiguous delivered IDs do not prove every compositor frame captured.']}
(r/'independent-roi-ab-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
