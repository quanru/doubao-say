import os,sys,pathlib,subprocess,json,time,hashlib,shutil
R=pathlib.Path('/tmp/pr12248'); E=R/'evidence'; H=pathlib.Path.home(); O=pathlib.Path('/usr/share/omarchy')
files=['bin/omarchy-disk-speedtest','bin/omarchy-menu-images','shell/plugins/panels/disk-speedtest/Panel.qml']
def run(*a):return subprocess.check_output(a,text=True,stderr=subprocess.STDOUT).strip()
def save(n,x): (E/(n+'.json')).write_text(json.dumps(x,indent=2));return x
def hashes(p):return {str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file() and not f.is_symlink()}
def snap():
 ps=[]
 for p in pathlib.Path('/proc').glob('[0-9]*'):
  try:
   cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
   if 'omarchy-disk-speedtest' not in cmd and not (p/'comm').read_text().strip()=='dd':continue
   if 'guest.py' in cmd or 'ssh' in cmd:continue
   fds={}
   for f in (p/'fd').iterdir():
    try:fds[f.name]={'target':os.readlink(f),'info':(p/'fdinfo'/f.name).read_text()}
    except OSError:pass
   stat=(p/'stat').read_text().split();ps.append({'pid':int(p.name),'ppid':int(stat[3]),'start_ticks':stat[21],'state':stat[2],'cmd':cmd,'fds':fds})
  except OSError:pass
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
 E.mkdir(exist_ok=True);(R/'config-before.json').write_text(json.dumps(hashes(H/'.config')))
 d=H/'.cache/omarchy';d.mkdir(parents=True,exist_ok=True)
 assert shutil.disk_usage(d).free>=3*1024**3
 assert not snap()['temporary_files'],'Existing test files in fresh VM'
 p=d/'acceptance-direct-io.dat'
 try:
  run('dd','if=/dev/zero','of='+str(p),'bs=4M','count=1','oflag=direct','status=none')
  run('dd','if='+str(p),'of=/dev/null','bs=4M','iflag=direct','status=none')
 finally:p.unlink(missing_ok=True)
 save('preflight',{'df':run('df','-h',str(d)),'mount':run('findmnt','-no','SOURCE,FSTYPE,OPTIONS','--target',str(d)),'block':run('lsblk','-J'),'direct_io_probe':True,'config_before':hashes(H/'.config'),'package_versions':run('pacman','-Q','hyprland','quickshell','bash','coreutils')})
elif c=='switch':switch(sys.argv[2])
elif c=='open':run('omarchy-shell','shell','summon','omarchy.disk-speedtest','{}')
elif c=='snapshot':print(json.dumps(save(sys.argv[2],snap())))
elif c=='status':print(json.dumps(snap()))
elif c=='screenshot':run('grim',str(E/(sys.argv[2]+'.png')))
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
 s=snap();assert not s['processes'] and not s['temporary_files'],s
 before=json.loads((R/'config-before.json').read_text());after=hashes(H/'.config');save('restore',{'snapshot':s,'config_byte_identical':before==after,'config_before':before,'config_after':after})
 assert before==after,'Configuration changed'
else:raise SystemExit('Unknown operation')
