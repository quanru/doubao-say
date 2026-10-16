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
 artifacts=api(f'actions/runs/{current}/artifacts')['artifacts']; candidates=[a for a in artifacts if '-pages-' in a['name'] and not a['expired']];assert len(candidates)==1,candidates
 a=candidates[0]
 subprocess.run(['gh','run','download',current,'-R','quanru/doubao-say','-n',a['name'],'-D','/tmp/pages13930-artifact'],check=True)
 site.mkdir()
 with tarfile.open('/tmp/pages13930-artifact/artifact.tar') as t:t.extractall(site,filter='data')
 assert (site/'reports/manifest.json').read_bytes()==live,'Artifact is not the live manifest; stop without deploy'
 assert (site/'index.html').read_bytes()==get('index.html')[0],'Root mismatch; stop without deploy'
 assert not target.exists(),'Isolated path already exists; do not overwrite'
 before={str(f.relative_to(site)):sha(f.read_bytes()) for f in site.rglob('*') if f.is_file()}
 src=pathlib.Path('/tmp/pr13930-delivery')
 archive=pathlib.Path('acceptance/omarchy-13930/delivery/omarchy-13930-report.zip')
 assert sha(archive.read_bytes())=='5c6daad2fe77da53dc6037cfe96308703b91f9cf036cf2542035c0ae45976ed4'
 with zipfile.ZipFile(archive) as z:z.extractall(src)
 src=src/'omarchy-13930-report'; files=[f for f in src.rglob('*') if f.is_file()]; mapping={str(f.relative_to(src)):str(f.relative_to(src)).replace('/','-').lower() for f in files};assert len(set(mapping.values()))==len(mapping)
 target.mkdir(parents=True)
 for f in files:
  rel=str(f.relative_to(src)); data=f.read_bytes()
  if f.suffix=='.html' and not rel.startswith('raw/'):
   def replace(m):
    url=m[2]
    if re.match(r'https?:|data:|#',url):return m[0]
    path=os.path.normpath(str(f.parent.relative_to(src)/url));assert path in mapping,(rel,path)
    return m[1]+'="'+mapping[path]+'"'
   data=re.sub(r'(href|src)="([^"]+)"',replace,data.decode()).encode()
   if rel=='index.html':data=data.replace(b'<h1>',b'<p>Published with owner authorization on 2026-10-16. The reviewed report below is the frozen 2026-10-15 delivery; its earlier publication-status statements refer to that delivery time.</p><h1>',1)
  (target/mapping[rel]).write_bytes(data)
 newfiles=[str(f.relative_to(site)) for f in target.iterdir()]
 manifest['reports'].insert(0,dict(runId='38748420827',generatedAt='2026-10-15T16:15:23Z',label='Omarchy PR13930 / 37 recorded steps / scoped acceptance',successRate=100,testCount=37,modelCallCount=0,averageDurationMs=None,tokenUsage=0,workflowUrl='https://github.com/quanru/doubao-say/actions/runs/38748420827',reportPath=prefix+'/index.html',files=newfiles,entries=[]))
 (site/'reports/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 assert all(sha((site/f).read_bytes())==v for f,v in before.items() if f!='reports/manifest.json')
 assert get('reports/manifest.json')[0]==live,'Concurrent update; stop without deploy'
 audit={'existing_file_count':len(before),'existing_root_sha256':before['index.html'],'original_manifest_sha256':sha(live),'existing_report_count':len(manifest['reports'])-1,'new_files':{f:sha((site/f).read_bytes()) for f in newfiles},'restored_artifact':a['id'],'restored_run':current,'preservation':'All previous files byte-identical except additive manifest registration; root unchanged.'}
 pathlib.Path('/tmp/pr13930-publication-audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps({k:v for k,v in audit.items() if k!='new_files'}))
else:
 audit=json.loads(pathlib.Path('/tmp/pr13930-publication-audit.json').read_text())
 def verify(item):
  f,h=item;b,ct=get(f);assert sha(b)==h,f
  if f.endswith('.png'):assert ct=='image/png',ct
  if f.endswith('.html'):assert ct=='text/html',ct
  return f
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex: verified=list(ex.map(verify,audit['new_files'].items()))
 assert sha(get('index.html')[0])==audit['existing_root_sha256']
 m=json.loads(get('reports/manifest.json')[0]);assert len(m['reports'])==audit['existing_report_count']+1
 print(json.dumps({'anonymous_endpoints_sha256_verified':len(verified),'root_preserved':True,'report_url':BASE+prefix+'/index.html'}))
