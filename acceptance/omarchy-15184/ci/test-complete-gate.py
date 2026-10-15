"""Unit tests only: synthetic records in temporary dirs, never acceptance evidence."""
from pathlib import Path
import copy,json,os,shutil,subprocess,tempfile,unittest
CI=Path(__file__).resolve().parent
class GateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.r=self.root/'review-artifacts';self.env={**os.environ,'ACCEPTANCE_SUITE':'timing-and-gui','GITHUB_RUN_ID':'12345','GITHUB_SHA':'a'*40}
  self.state={'processes':[{'pid':i,'start_ticks':i*10,'comm':n} for i,n in enumerate(['fcitx5','python3','quickshell'],1)],'info':{'data':['us',[['keyboard-us',''],['pinyin','']]]}}
  self.put('guest/gui-state-0.json',self.state);self.put('guest/restore.json',{'config_byte_identical':True});self.put('guest/candidate-integrity.json',{'mismatches':[]});self.put('guest/composition.json',{'committed':'你好\n你好\n你好'})
  rows=[]
  for i in range(1,4):
   removed=copy.deepcopy(self.state);removed['info']['data'][1]=[['keyboard-us','']]
   rows.append({'round':i,'status':'OPERATIONS_PASS_VISUAL_REVIEW_PENDING','processesUnchanged':True,'controllerWrites':False,'removeSelection':{'node':{'name':'Pinyin'}},'addSelection':{'node':{'name':'Pinyin'}},'removed':removed,'restored':self.state})
   for stage in ['removed','restored']:(self.r/'guest'/f'gui-{i}-{stage}.png').write_bytes(b'UNIT ONLY - image content is not tested by operation gate')
  rows.append({'case':'restore-original-list-and-compose','status':'PASS','committedBefore':'你好\n你好','committedAfter':'你好\n你好\n你好'})
  self.put('gui-results.json',rows)
  pins=json.loads((CI/'pins.json').read_text());self.put('versions/source-pins.json',pins)
  timing=[{'trial':f'{p}{i:02}','status':'PASS','metrics':{'keydown':{'lower_ms':100,'upper_ms':200,'status':'PASS'}},'requested_hold_ms':80 if p=='switch' else 5} for p in ['switch','quick'] for i in range(20)]
  for prefix in ['plain/','']:
   self.put(prefix+'latency-results.json',timing);self.put(prefix+'model-usage.json',{'requests':0,'cost_cny':0,'credentials_injected':False})
 def tearDown(self):self.tmp.cleanup()
 def put(self,name,value):
  p=self.r/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
 def get(self,name):return json.loads((self.r/name).read_text())
 def call(self,name):return subprocess.run(['python3',str(CI/name)],cwd=self.root,env=self.env,capture_output=True,text=True)
 def test_full_sequence(self):
  self.assertEqual(self.call('verify-gui-operations.py').returncode,0);result=self.call('verify-complete.py');self.assertEqual(result.returncode,0,result.stderr);r=self.get('complete-operation-verification.json');self.assertEqual(r['source_run'],12345);self.assertEqual(sum(x['trials'] for x in r['timing_groups'].values()),80);self.assertEqual(r['visual_review'],'PENDING')
 def test_rejects_missing_duplicate_over_threshold_inconclusive_and_wrong_hold(self):
  self.assertEqual(self.call('verify-gui-operations.py').returncode,0);original=self.get('plain/latency-results.json')
  for kind in ['missing','duplicate','slow','uncertain','wronghold','nan']:
   with self.subTest(kind=kind):
    x=copy.deepcopy(original)
    if kind=='missing':x.pop()
    if kind=='duplicate':x[1]=x[0]
    if kind=='slow':x[0]['metrics']['keydown']['upper_ms']=500.001
    if kind=='uncertain':x[0]['status']='INCONCLUSIVE'
    if kind=='wronghold':x[0]['requested_hold_ms']=5
    if kind=='nan':x[0]['metrics']['keydown']['upper_ms']=float('nan')
    self.put('plain/latency-results.json',x);self.assertNotEqual(self.call('verify-complete.py').returncode,0)
 def test_rejects_no_fresh_commit_wrong_engine_restart_and_cleanup_failure(self):
  orig=self.get('gui-results.json')
  for kind in ['stale','wrongengine','restart','extra_failure']:
   with self.subTest(kind=kind):
    x=copy.deepcopy(orig)
    if kind=='stale':x[-1]['committedAfter']=x[-1]['committedBefore']
    if kind=='wrongengine':x[0]['addSelection']['node']['name']='Wubi Pinyin'
    if kind=='restart':x[0]['removed']['processes'][0]['start_ticks']+=1
    if kind=='extra_failure':x.append({'status':'BLOCKED_OR_FAILED'})
    self.put('gui-results.json',x);self.assertNotEqual(self.call('verify-gui-operations.py').returncode,0)
  self.put('gui-results.json',orig);self.put('guest/restore.json',{'config_byte_identical':False});self.assertNotEqual(self.call('verify-gui-operations.py').returncode,0)
 def test_rejects_stale_provenance_and_model_usage(self):
  self.assertEqual(self.call('verify-gui-operations.py').returncode,0);self.env['GITHUB_RUN_ID']='12346';self.assertNotEqual(self.call('verify-complete.py').returncode,0);self.env['GITHUB_RUN_ID']='12345';self.put('plain/model-usage.json',{'requests':1,'cost_cny':0,'credentials_injected':False});self.assertNotEqual(self.call('verify-complete.py').returncode,0)
 def test_gui_only_has_no_old_timing_reference(self):
  self.env['ACCEPTANCE_SUITE']='gui';rows=self.get('gui-results.json');rows[-1].update(committedBefore='',committedAfter='你好');self.put('gui-results.json',rows);self.put('guest/composition.json',{'committed':'你好'});self.assertEqual(self.call('verify-gui-operations.py').returncode,0);self.assertEqual(self.call('verify-complete.py').returncode,0);self.assertEqual(self.get('complete-operation-verification.json')['timing_groups'],{});self.assertNotIn('38548301623',(self.r/'gui-operation-verification.json').read_text())
 def test_actual_finalizer_runs_every_gate_and_preserves_failure(self):
  c=self.root/'ci';c.mkdir();shutil.copy2(CI/'finalize.sh',c/'finalize.sh')
  stub="import os,sys\nfrom pathlib import Path\nname=Path(__file__).name+(' plain' if len(sys.argv)>1 else '')\nwith open('calls','a') as f:f.write(name+'\\n')\nraise SystemExit(1 if os.environ.get('FAIL_GATE')==name else 0)\n"
  for n in ['analyze-native.py','verify-gui-operations.py','verify-complete.py']:(c/n).write_text(stub)
  expected=['analyze-native.py plain','analyze-native.py','verify-gui-operations.py','verify-complete.py']
  for fail in ['',*expected]:
   with self.subTest(fail=fail):
    (self.root/'calls').unlink(missing_ok=True);p=subprocess.run(['bash','ci/finalize.sh'],cwd=self.root,env={**self.env,'FAIL_GATE':fail},capture_output=True,text=True);self.assertEqual(p.returncode,1 if fail else 0,p.stderr);self.assertEqual((self.root/'calls').read_text().splitlines(),expected)
if __name__=='__main__':unittest.main()
