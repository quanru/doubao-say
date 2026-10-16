import pathlib,subprocess,json,urllib.request,zipfile,tarfile,hashlib,re,sys,os,concurrent.futures
BASE='https://quanru.github.io/doubao-say/'
site=pathlib.Path('/tmp/pages13930'); prefix='reports/38748420827'; target=site/prefix
sha=lambda b:hashlib.sha256(b).hexdigest()
def get(path):
 with urllib.request.urlopen(BASE+path,timeout=90) as r:
  assert r.status==200
  return r.read(),r.headers.get_content_type()
def api(path):return json.loads(subprocess.check_output(['gh','api','repos/quanru/doubao-say/'+path]))
if sys.argv[1]=='prepare':
 live,_=get('reports/manifest.json'); manifest=json.loads(live); current=manifest['reports'][0]['runId']
 candidates=[a for a in api('actions/artifacts?per_page=100')['artifacts'] if 'pages' in a['name'] and not a['expired']]
 selected=None
 for a in candidates[:12]:
  directory=f"/tmp/pages13930-artifact-{a['id']}"
  subprocess.run(['gh','run','download',str(a['workflow_run']['id']),'-R','quanru/doubao-say','-n',a['name'],'-D',directory],check=True)
  archive=pathlib.Path(directory)/'artifact.tar'
  if not archive.exists():continue
  with tarfile.open(archive) as t:
   member=next((m for m in t.getmembers() if m.name.lstrip('./')=='reports/manifest.json'),None)
   if member and t.extractfile(member).read()==live:selected=(a,archive);break
 assert selected,'No complete artifact matching the live site; stop without deploy'
 a,archive=selected;current=str(a['workflow_run']['id']);site.mkdir()
 with tarfile.open(archive) as t:t.extractall(site,filter='data')
 assert (site/'index.html').read_bytes()==get('index.html')[0],'Root mismatch; stop without deploy'
 assert target.is_dir(),'Existing isolated report required'
 before={str(f.relative_to(site)):sha(f.read_bytes()) for f in site.rglob('*') if f.is_file()}
 if os.environ.get('DRAFT_ONLY')=='1':
  (target/'english-pr-reply-draft.txt').write_bytes(pathlib.Path('acceptance/omarchy-13930/publish/comment.md').read_bytes())
  newfiles=[str(f.relative_to(site)) for f in target.iterdir()]
  assert all(sha((site/f).read_bytes())==v for f,v in before.items() if f!=prefix+'/english-pr-reply-draft.txt'),'Unexpected change outside draft'
 else:
  from english import build
  build(target)
  original=pathlib.Path('acceptance/omarchy-13930/delivery/omarchy-13930-original-evidence.tar.gz').read_bytes()
  assert sha(original)=='b9317f0f708fb3ba31c90b04c72b0da1ce133f4f7eff9005bb4f0ce0644b683e'
  (target/'original-evidence.tar.gz').write_bytes(original)
  (target/'english-pr-reply-draft.txt').write_text(pathlib.Path('acceptance/omarchy-13930/publish/comment.md').read_text())
  newfiles=[str(f.relative_to(site)) for f in target.iterdir()]
  record=next(r for r in manifest['reports'] if r['runId']=='38748420827');record['files']=newfiles
  (site/'reports/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  assert all(sha((site/f).read_bytes())==v for f,v in before.items() if f!='reports/manifest.json' and not (f.startswith(prefix+'/evidence-') or f in [prefix+'/index.html',prefix+'/english-pr-reply-draft.txt']))
 assert get('reports/manifest.json')[0]==live,'Concurrent update; stop without deploy'
 audit={'existing_file_count':len(before),'existing_root_sha256':before['index.html'],'original_manifest_sha256':sha(live),'existing_report_count':len(manifest['reports']),'new_files':{f:sha((site/f).read_bytes()) for f in newfiles},'restored_artifact':a['id'],'restored_run':current,'preservation':('Only english-pr-reply-draft.txt changed; every other existing file, including manifest and all HTML, is byte-identical.' if os.environ.get('DRAFT_ONLY')=='1' else 'Only presentation files changed; original evidence unchanged.')}
 pathlib.Path('/tmp/pr13930-publication-audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps({k:v for k,v in audit.items() if k!='new_files'}))
else:
 audit=json.loads(pathlib.Path('/tmp/pr13930-publication-audit.json').read_text())
 def verify(item):
  f,h=item;b,ct=get(f);assert sha(b)==h,f
  if f.endswith('.png'):assert ct=='image/png',ct
  if f.endswith('.html'):
   assert ct=='text/html',ct
   if '/raw-' not in f:assert not re.search(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]',b.decode()),f
  return f
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex: verified=list(ex.map(verify,audit['new_files'].items()))
 assert sha(get('index.html')[0])==audit['existing_root_sha256']
 m=json.loads(get('reports/manifest.json')[0]);assert len(m['reports'])==audit['existing_report_count']
 print(json.dumps({'anonymous_endpoints_sha256_verified':len(verified),'root_preserved':True,'report_url':BASE+prefix+'/index.html'}))
