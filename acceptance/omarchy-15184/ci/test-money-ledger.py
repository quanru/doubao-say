"""Offline monetary cap tests, no inference or real acceptance claim."""
import importlib.util,tempfile
from pathlib import Path
s=importlib.util.spec_from_file_location('money',Path(__file__).resolve().parents[1]/'scripts/money-ledger.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'ledger.jsonl';l=m.Ledger(p,20_000_000,9_437_184)
 a=l.reserve();b=l.reserve();assert l.reserve() is None
 assert not l.settle(a,None,0);assert l.used==18_874_368
 l.file.close();l=m.Ledger(p,20_000_000,9_437_184)
 assert l.reserve() is None # Failed/in-flight calls survive process restart.
 assert l.settle(a,1000,1000);assert l.used==9_473_184
 assert l.reserve() is not None
 assert l.reserve() is None
 try: m.Ledger(p,20_000_000,9_437_184)
 except BlockingIOError: pass
 else: raise AssertionError('second writer acquired ledger')
 l.file.close()
print('PASS: reservation before send, cumulative reload, failure retention, usage validation, exclusive lock. Offline only.')
