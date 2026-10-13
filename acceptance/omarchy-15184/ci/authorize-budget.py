"""Validate an agent-maintained public budget allocation; never calls a model."""
import json,os,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
assert p['currency']=='CNY' and p['task_limit_micro']==100_000_000
assert p['model']=='doubao-seed-2-1-turbo-260628'
alloc=p['allocations']; assert len({a['run_id'] for a in alloc})==len(alloc)
assert all(type(a['micro_cny'])==int and 0<a['micro_cny']<=100_000_000 for a in alloc)
assert sum(a['micro_cny'] for a in alloc)<=100_000_000
assert os.environ.get('GITHUB_REPOSITORY')=='quanru/doubao-say'
assert os.environ.get('GITHUB_REF')=='refs/heads/acceptance/omarchy-15184-a1ead6b3'
assert os.environ.get('GITHUB_RUN_ATTEMPT')=='1','Reruns require a new unique allocated run'
a=[a for a in alloc if str(a['run_id'])==os.environ.get('GITHUB_RUN_ID')]
assert len(a)==1,'This unique run has no budget allocation'
assert a[0]['micro_cny']>=p['request_reservation_micro']
print(a[0]['micro_cny'])
