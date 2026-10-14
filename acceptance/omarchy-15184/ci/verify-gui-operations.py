"""Check real GUI operation records. Visual review remains a separate requirement."""
from pathlib import Path
import json
r=Path('review-artifacts');read=lambda p:json.loads(p.read_text());rows=read(r/'gui-results.json')
identity=lambda s:sorted((p['pid'],p['start_ticks'],p['comm']) for p in s['processes'])
rounds=[x for x in rows if 'round' in x];assert [x['round'] for x in rounds]==[1,2,3]
initial=read(r/'guest/gui-state-0.json');ids=identity(initial);assert len(ids)==3
for x in rounds:
 assert x['status']=='OPERATIONS_PASS_VISUAL_REVIEW_PENDING' and x['processesUnchanged'] and not x['controllerWrites']
 assert x['removeSelection']['node']['name']=='Pinyin' and x['addSelection']['node']['name']=='Pinyin'
 for key,expected in [('removed',['keyboard-us']),('restored',['keyboard-us','pinyin'])]:
  assert identity(x[key])==ids and [v[0] for v in x[key]['info']['data'][1]]==expected
 for stage in ['removed','restored']:assert (r/'guest'/f'gui-{x["round"]}-{stage}.png').is_file()
final=[x for x in rows if x.get('case')=='restore-original-list-and-compose'];assert len(final)==1 and final[0]['status']=='PASS'
assert final[0]['committedAfter'].count('你好')==final[0]['committedBefore'].count('你好')+1
assert read(r/'guest/restore.json')['config_byte_identical'] is True
assert not read(r/'guest/candidate-integrity.json')['mismatches']
(r/'gui-operation-verification.json').write_text(json.dumps({'three_rounds':True,'exact_engine':'pinyin','processes_unchanged':True,'fresh_chinese_commit':True,'byte_restore':True,'visual_review':'PENDING','timing_trials_this_run':0,'timing_source_run':38548301623},indent=2))
(r/'model-usage.json').write_text(json.dumps({'requests':0,'cost_cny':0,'credentials_injected':False},indent=2))
print('PASS GUI operations only: 3 exact-Pinyin rounds, unchanged processes, fresh composition and byte restoration. Visual review pending; timing not repeated.')
