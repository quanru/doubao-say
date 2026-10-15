import os,sys,pathlib,subprocess,json,time,hashlib,shutil
R=pathlib.Path('/tmp/pr12248'); E=R/'evidence'; H=pathlib.Path.home(); O=pathlib.Path('/usr/share/omarchy')
import importlib.util
spec=importlib.util.spec_from_file_location('config_evidence',R/'config-evidence.py');config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
files=['bin/omarchy-disk-speedtest','bin/omarchy-menu-images','shell/plugins/panels/disk-speedtest/Panel.qml']
def run(*a):return subprocess.check_output(a,text=True,stderr=subprocess.STDOUT).strip()
def save(n,x): (E/(n+'.json')).write_text(json.dumps(x,indent=2));return x
def hashes(p):return {str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file() and not f.is_symlink()}
def snap():
 allps={}
 for p in pathlib.Path('/proc').glob('[0-9]*'):
  try:
   cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
   stat=(p/'stat').read_text().split()
   allps[int(p.name)]={'pid':int(p.name),'ppid':int(stat[3]),'start_ticks':stat[21],'state':stat[2],'cmd':cmd,'comm':(p/'comm').read_text().strip()}
  except OSError:pass
 tracked=R/'tracked-processes.json';old=json.loads(tracked.read_text()) if tracked.exists() else {}
 selected={pid for pid,p in allps.items() if (('omarchy-disk-speedtest' in p['cmd'] or p['comm']=='dd') and 'guest.py' not in p['cmd'] and 'ssh' not in p['cmd']) or old.get(str(pid))==p['start_ticks']}
 while True:
  new={pid for pid,p in allps.items() if p['ppid'] in selected}
  if new<=selected:break
  selected|=new
 ps=[]
 for pid in sorted(selected):
  entry=allps[pid];p=pathlib.Path('/proc',str(pid));fds={}
  try:
   for f in (p/'fd').iterdir():
    try:fds[f.name]={'target':os.readlink(f),'info':(p/'fdinfo'/f.name).read_text()}
    except OSError:pass
  except OSError:pass
  entry['fds']=fds;ps.append(entry)
 tracked.write_text(json.dumps({str(p['pid']):p['start_ticks'] for p in ps}))
 ts=list((H/'.cache/omarchy').glob('disk-speedtest-*.dat'))+list(pathlib.Path('/dev/shm').glob('omarchy-disk-speedtest-*.src'))
 return {'time_ns':time.monotonic_ns(),'processes':ps,'temporary_files':[{'path':str(p),'size':p.stat().st_size} for p in ts],'layers':run('hyprctl','-j','layers')}
def switch(v):
 assert v in ['baseline','head']
 subprocess.run(['quickshell','kill','-p',str(O/'shell'),'--any-display'],check=False)
 time.sleep(1)
 for f in files:
  subprocess.run(['sudo','-S','install','-m','755' if f.startswith('bin/') else '644',str(R/'sources'/v/f),str(O/f)],input='omarchy\n',text=True,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run('hyprctl','dispatch','hl.dsp.exec_cmd("omarchy-restart-shell")')
 for _ in range(80):
  try:run('omarchy-shell','shell','ping');break
  except subprocess.CalledProcessError:time.sleep(.25)
 else:raise RuntimeError('Shell not ready')
 time.sleep(1)
 actual={f:hashlib.sha256((O/f).read_bytes()).hexdigest() for f in files}
 assert actual=={f:hashlib.sha256((R/'sources'/v/f).read_bytes()).hexdigest() for f in files}
 save(v+'-installed',actual)
c=sys.argv[1]
if c=='bootstrap':
 E.mkdir(exist_ok=True)
 cfg=H/'.config/omarchy/shell.json'
 if cfg.exists():shutil.copy2(cfg,R/'shell-config-backup')
 (R/'config-before.json').write_text(json.dumps(hashes(H/'.config')))
 config.capture('before')
 p=subprocess.Popen([sys.executable,str(R/'config-evidence.py')],stdout=open(E/'config-watch.log','w'),stderr=subprocess.STDOUT,start_new_session=True)
 save('config-watch-start',{'pid':p.pid})
 d=H/'.cache/omarchy';d.mkdir(parents=True,exist_ok=True)
 assert shutil.disk_usage(d).free>=3*1024**3
 assert not snap()['temporary_files'],'Existing test files in fresh VM'
 p=d/'acceptance-direct-io.dat'
 try:
  run('dd','if=/dev/zero','of='+str(p),'bs=4M','count=1','oflag=direct','status=none')
  run('dd','if='+str(p),'of=/dev/null','bs=4M','iflag=direct','status=none')
 finally:p.unlink(missing_ok=True)
 save('preflight',{'df':run('df','-h',str(d)),'mount':run('findmnt','-no','SOURCE,FSTYPE,OPTIONS','--target',str(d)),'block':run('lsblk','-J'),'direct_io_probe':True,'config_before':hashes(H/'.config'),'package_versions':run('pacman','-Q','hyprland','quickshell','bash','coreutils')})
elif c=='switch':
 (R/'case-label').write_text('switch-'+sys.argv[2]);config.capture('before-switch-'+sys.argv[2]);switch(sys.argv[2]);config.capture('after-switch-'+sys.argv[2])
elif c=='open':run('omarchy-shell','shell','summon','omarchy.disk-speedtest','{}')
elif c=='snapshot':
 (R/'case-label').write_text(sys.argv[2]);config.capture(sys.argv[2]);print(json.dumps(save(sys.argv[2],snap())))
elif c=='status':print(json.dumps(snap()))
elif c=='screenshot':run('grim',str(E/(sys.argv[2]+'.png')))
elif c=='cancel-ready':
 label=sys.argv[2];assert label in ['baseline','head']
 def staging_snapshot():
  x=snap();dd=[p for p in x['processes'] if p['cmd'].startswith('dd ')]
  assert len(dd)==4 and all('oflag=direct' in p['cmd'] for p in dd),'Cancel point is not staging'
  remaining=sum(max(0,256*1024*1024-f['size']) for f in x['temporary_files'] if f['path'].endswith('.dat'))
  assert remaining>=128*1024*1024,'Insufficient genuine staging work remaining for unambiguous cancellation'
  return x,remaining
 before,_=staging_snapshot();path=pathlib.Path('/dev/shm')/('pr12248-cancel-'+label+'.png');start=time.monotonic_ns();run('grim',str(path));finish=time.monotonic_ns()
 after,remaining=staging_snapshot()
 d={'before':before,'after':after,'capture_start_ns':start,'capture_end_ns':finish,'remaining_staging_bytes':remaining,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 (path.with_suffix('.json')).write_text(json.dumps(d,indent=2))
 print(json.dumps({'capture_start_ns':start,'capture_end_ns':finish,'remaining_staging_bytes':remaining,'old':[[p['pid'],p['start_ticks']] for p in after['processes']]}))
elif c=='cancel-image':
 import base64
 label=sys.argv[2];assert label in ['baseline','head'];p=pathlib.Path('/dev/shm')/('pr12248-cancel-'+label+'.png')
 shutil.copy2(p,E/(label+'-cancel-staging.png'));shutil.copy2(p.with_suffix('.json'),E/(label+'-cancel-input-proof.json'))
 proof=json.loads(p.with_suffix('.json').read_text());save(label+'-cancel-before',proof['after'])
 print(base64.b64encode(p.read_bytes()).decode())
elif c=='observe-start':
 label=sys.argv[2];assert label in ['baseline','baseline-reopen','head','head-reopen']
 d=pathlib.Path('/dev/shm/pr12248-observer')/label
 p=subprocess.Popen([sys.executable,str(R/'observe-write.py'),label],stdout=open(E/(label+'-observer.log'),'w'),stderr=subprocess.STDOUT,start_new_session=True)
 for _ in range(100):
  if (d/'ready').exists():break
  if p.poll() is not None:raise RuntimeError('Observer failed before ready')
  time.sleep(.02)
 else:raise RuntimeError('Observer not ready')
 save(label+'-observer-start',{'pid':p.pid,'label':label})
elif c=='observe-result':
 label=sys.argv[2];d=pathlib.Path('/dev/shm/pr12248-observer')/label
 for _ in range(200):
  if (d/'done').exists():break
  time.sleep(.05)
 else:raise RuntimeError('Observer has not finished preserving evidence')
 result=json.loads((d/'observation.json').read_text());assert not result['error'],result['error']
 print(json.dumps({'label':label,'status':result['status'],'frames':[{k:f[k] for k in ['name','path','full_screen','capture_start_ns','capture_end_ns','capture_epoch_ns','sha256']} for f in result['frames']]}))
elif c=='observe-image':
 import base64
 label,name=sys.argv[2:4];assert label in ['baseline','baseline-reopen','head','head-reopen'] and name in ['read-live','write-live-first','write-live-sampled','completed']
 print(base64.b64encode((pathlib.Path('/dev/shm/pr12248-observer')/label/(name+'.png')).read_bytes()).decode())
elif c=='picker-prepare':
 import struct,zlib
 d=R/'images';d.mkdir(exist_ok=True)
 def chunk(k,b):return struct.pack('!I',len(b))+k+b+struct.pack('!I',zlib.crc32(k+b)&0xffffffff)
 for n,col in [('a-red',(200,40,40)),('b-green',(40,180,70)),('c-blue',(40,80,210))]:
  raw=b''.join(b'\0'+bytes(col)*320 for _ in range(200))
  (d/(n+'.png')).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',320,200,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
 save('image-fixtures',hashes(d))
elif c=='picker-start':
 variant,round=sys.argv[2:4];assert variant in ['baseline','head'] and round in ['cold','warm','index']
 cache=R/('cache-'+variant)
 if round=='cold':assert not cache.exists(),'Cold cache already exists'
 if round=='index':
  for f in (cache/'omarchy/image-selector').glob('*'):
   if f.suffix in ['.rows','.signature','.fast-signature']:f.unlink()
 subprocess.Popen([sys.executable,__file__,'picker-worker',variant,round],stdout=open(E/(variant+'-picker-'+round+'.log'),'w'),stderr=subprocess.STDOUT,start_new_session=True)
 print('started')
elif c=='picker-worker':
 variant,round=sys.argv[2:4];env=dict(os.environ,XDG_CACHE_HOME=str(R/('cache-'+variant)))
 start=time.monotonic_ns()
 p=subprocess.run(['omarchy-menu-images','--show-labels','--selected',str(R/'images/b-green.png'),str(R/'images')],env=env,text=True,capture_output=True,timeout=60)
 cache=R/('cache-'+variant)/'omarchy/image-selector'
 save(variant+'-picker-'+round,{'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'duration_ns':time.monotonic_ns()-start,'cache_hashes':hashes(cache),'index':(cache/'index.tsv').read_text() if (cache/'index.tsv').exists() else None})
elif c=='picker-result':
 p=E/(sys.argv[2]+'-picker-'+sys.argv[3]+'.json');print(p.read_text() if p.exists() else '{}')
elif c=='restore':
 run('omarchy-shell','shell','hide','omarchy.disk-speedtest');time.sleep(2);switch('head')
 s=snap();cleanup_ok=not s['processes'] and not s['temporary_files'];save('restore-entry-cleanup',s)
 before=json.loads((R/'config-before.json').read_text());pre=hashes(H/'.config');config.capture('pre-restore')
 save('pre-restore',{'snapshot':s,'config_byte_identical':before==pre,'config_before':before,'config_after':pre})
 # Stop the actual shell before restoring so an asynchronous FileView write cannot race the copy.
 for _ in range(10):
  p=subprocess.run(['quickshell','kill','-p',str(O/'shell'),'--any-display'],capture_output=True,text=True,timeout=8)
  if p.returncode!=0:break
 else:raise RuntimeError('Shell instances did not stop')
 def shell_pids():
  out=[]
  for p in pathlib.Path('/proc').glob('[0-9]*'):
   try:
    cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
    if (p/'comm').read_text().strip() in ['quickshell','qs'] and str(O/'shell') in cmd:out.append({'pid':int(p.name),'cmd':cmd})
   except OSError:pass
  return out
 time.sleep(1);stopped=shell_pids();save('shell-stopped',{'processes':stopped});assert not stopped,'Shell writer still alive'
 config.capture('quiesced-before-restore');quiesced=hashes(H/'.config')
 changed=[n for n in set(before)|set(quiesced) if before.get(n)!=quiesced.get(n)]
 save('quiesced-config-diff',{'changed_files':changed,'before':before,'after':quiesced})
 assert not [n for n in changed if n!='omarchy/shell.json'],'Unexpected non-shell config changes; refusing broad restore'
 cfg=H/'.config/omarchy/shell.json';backup=R/'shell-config-backup'
 if backup.exists():shutil.copy2(backup,cfg)
 else:cfg.unlink(missing_ok=True)
 config.capture('after-restore');checks=[]
 for _ in range(12):
  time.sleep(.25);after=hashes(H/'.config');checks.append({'epoch_ns':time.time_ns(),'config_equal':before==after,'shell_processes':shell_pids()})
  assert before==after and not checks[-1]['shell_processes'],'Restored configuration changed or shell writer restarted'
 (R/'config-watch-stop').touch()
 for _ in range(50):
  if (R/'config-watch-done').exists():break
  time.sleep(.1)
 assert (R/'config-watch-done').exists(),'Config observer did not finish'
 s=snap();final_cleanup_ok=not s['processes'] and not s['temporary_files']
 save('restore',{'snapshot':s,'pre_restore_config_byte_identical':before==pre,'config_byte_identical':before==after,'config_before':before,'config_after':after,'quiesced_changed_files':changed,'stable_checks':checks,'shell_stopped_for_final_disposable_vm_teardown':True,'entry_product_cleanup_ok':cleanup_ok,'final_product_cleanup_ok':final_cleanup_ok})
 assert before==after,'Configuration restore failed'
 assert cleanup_ok and final_cleanup_ok,'Product cleanup failed; evidence preserved and configuration restored separately'
else:raise SystemExit('Unknown operation')
