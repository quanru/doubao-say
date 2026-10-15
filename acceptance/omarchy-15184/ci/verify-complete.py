"""Fail-closed final gate for this run only. Screenshot review stays separate."""
from pathlib import Path
import json,math,os,re
r=Path('review-artifacts')
read=lambda p:json.loads(p.read_text())
suite=os.environ.get('ACCEPTANCE_SUITE','timing-and-gui')
assert suite in ['gui','timing-and-gui']
run=int(os.environ['GITHUB_RUN_ID']);assert run>0
sha=os.environ['GITHUB_SHA'];assert re.fullmatch('[a-f0-9]{40}',sha)
pins=read(r/'versions/source-pins.json')
assert pins['omarchy']=='a843315558d77a9f914ca1dc2b7d6c1b005ce239'
assert pins['midscene_commit']=='852410869c665bbb32f1017d51103fb768e01b07'
gui=read(r/'gui-operation-verification.json')
assert gui['source_run']==run and gui['suite']==suite
assert all(gui[k] is True for k in ['three_rounds','processes_unchanged','fresh_chinese_commit','byte_restore'])
assert read(r/'guest/restore.json')['config_byte_identical'] is True
groups={}
if suite=='timing-and-gui':
 expected=[f'{prefix}{i:02}' for prefix in ['switch','quick'] for i in range(20)]
 for name,path in [('plain',r/'plain'),('pixels',r)]:
  rows=read(path/'latency-results.json')
  assert [x['trial'] for x in rows]==expected,(name,'Missing, duplicate or reordered trials')
  for i,x in enumerate(rows):
   metric=x['metrics']['keydown'];lo=metric['lower_ms'];hi=metric['upper_ms']
   assert all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in [lo,hi])
   assert 0<=lo<=hi<=500 and x['status']==metric['status']=='PASS',(name,x['trial'])
   assert x['requested_hold_ms']==(80 if i<20 else 5)
  groups[name]={'trials':40,'pass':40,'maximum_keydown_upper_ms':max(x['metrics']['keydown']['upper_ms'] for x in rows)}
 assert gui['committed_before_count']==2 and gui['committed_after_count']==3
for path in ([r/'plain',r] if suite=='timing-and-gui' else [r]):
 usage=read(path/'model-usage.json')
 assert usage['requests']==0 and usage['cost_cny']==0 and usage['credentials_injected'] is False
summary={'status':'AUTOMATED_GATES_PASS_VISUAL_REVIEW_PENDING','source_run':run,'harness_commit':sha,'suite':suite,'candidate_commit':pins['omarchy'],'midscene_commit':pins['midscene_commit'],'timing_groups':groups,'gui_rounds':3,'fresh_chinese_commit':True,'configuration_restored':True,'new_model_calls':0,'visual_review':'PENDING'}
(r/'complete-operation-verification.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
