import sys,subprocess,pathlib,json,hashlib,os,shutil,time
R=pathlib.Path('/tmp/pr15184');E=R/'evidence';E.mkdir(exist_ok=True)
def run(*args):return subprocess.check_output(args,text=True).strip()
def save(name,obj): (E/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def processes():
 out=[]
 for p in pathlib.Path('/proc').glob('[0-9]*'):
  try:
   comm=(p/'comm').read_text().strip()
   if comm in ['qs','quickshell','fcitx5','python3']:
    cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode()
    if comm=='python3' and '/default/input-methods/indicator.py' not in cmd:continue
    out.append({'pid':int(p.name),'comm':comm,'start_ticks':(p/'stat').read_text().split()[21],'cmd':cmd})
  except (OSError,UnicodeError):pass
 return out
def target_window():
 clients=json.loads(run('hyprctl','-j','clients'))
 matches=[c for c in clients if c.get('class')=='org.omarchy.pr15184' or c.get('initialClass')=='org.omarchy.pr15184']
 save('test-windows',[{k:c.get(k) for k in ['address','class','initialClass','title','pid']} for c in matches])
 assert len(matches)==1,'Expected one real test terminal window'
 return matches[0]
def focus_target():
 c=target_window();address=c['address']
 p=subprocess.run(['hyprctl','dispatch','hl.dsp.focus({ window = "address:'+address+'" })'],text=True,capture_output=True)
 if p.returncode:run('hyprctl','dispatch','focuswindow','address:'+address)
 active=json.loads(run('hyprctl','-j','activewindow'));assert active.get('address')==address,'Test terminal did not gain focus'
def snap():
 group=run('fcitx5-remote','-q')
 info=json.loads(run('busctl','--user','--json=short','call','org.fcitx.Fcitx5','/controller','org.fcitx.Fcitx.Controller1','InputMethodGroupInfo','s',group))
 return {'time_ns':time.monotonic_ns(),'group':group,'info':info,'active':run('fcitx5-remote'),'current':run('fcitx5-remote','-n'),'processes':processes()}
cmd=sys.argv[1]
if cmd=='bootstrap':
 manifest=json.loads((R/'source-manifest.json').read_text());bad=[]
 for name,digest in manifest.items():
  p=(pathlib.Path('/usr/bin')/pathlib.Path(name).name) if name.startswith('bin/') else pathlib.Path('/usr/share/omarchy')/name
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:bad.append(name)
 save('candidate-integrity',{'checked_files':len(manifest),'mismatches':bad})
 if bad:raise SystemExit('Installed runtime does not match complete candidate manifest')
 for command in ['fcitx5','fcitx5-configtool','fcitx5-config-qt','grim','hyprctl','foot']:assert shutil.which(command),command
 monitors=json.loads(run('hyprctl','-j','monitors'));assert len(monitors)==1 and monitors[0]['width']==1280 and monitors[0]['height']==800 and monitors[0]['scale']==1,'Require 1280x800 scale=1 guest for 1:1 VNC ROI'
 save('package-versions',{'graphics':run('hyprctl','systeminfo'),'packages':run('pacman','-Q'),'kernel':run('uname','-r'),'monitors':json.loads(run('hyprctl','-j','monitors'))})
 config=pathlib.Path.home()/'.config/fcitx5';shutil.copytree(config,R/'fcitx5-backup',symlinks=True)
 text=(config/'config').read_text();assert '[Hotkey/AltTriggerKeys]\n0=Shift_L' in text,'Expected real configured lone Shift trigger'
 initial=snap();assert 'pinyin' in json.dumps(initial['info']),'Pinyin must come from fresh ISO provisioning'
 assert any('/usr/share/omarchy/default/input-methods/indicator.py' in p['cmd'] for p in initial['processes']),'Candidate indicator not running'
 save('initial',initial)
 run('omarchy-shell','idle','disable')
 subprocess.Popen(['foot','--app-id=org.omarchy.pr15184','sh','-c','cat > /tmp/pr15184/committed.txt'],stdout=subprocess.DEVNULL,stderr=open(E/'terminal.log','a'),start_new_session=True)
 for _ in range(50):
  try:focus_target();break
  except (AssertionError,subprocess.CalledProcessError):time.sleep(.1)
 else:raise SystemExit('Test terminal focus preflight failed; see terminal.log')
 subprocess.run(['omarchy-shell','notifications','dismissAll'],check=False,stdout=subprocess.DEVNULL)
elif cmd=='preflight-report':
 for name in ['candidate-integrity','package-versions','initial']:
  obj=json.loads((E/(name+'.json')).read_text());print(json.dumps({name:obj},ensure_ascii=False))
elif cmd=='snapshot':
 obj=snap();save(sys.argv[2],obj);print(json.dumps(obj))
elif cmd=='screenshot':
 subprocess.run(['grim',str(E/(sys.argv[2]+'.png'))],check=True)
elif cmd=='configtool':
 subprocess.Popen(['fcitx5-configtool'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
elif cmd=='focus':
 focus_target()
elif cmd=='committed':
 s=(R/'committed.txt').read_text();assert any('\u4e00'<=c<='\u9fff' for c in s),'No actual committed Han text'
 save('composition',{'committed':s});print(s)
elif cmd=='template':
 x,y,w,h=map(int,sys.argv[3:7]);assert 0<=x<1280 and 0<=y<800 and 4<=w<=256 and 4<=h<=100
 subprocess.run(['grim','-g',f'{x},{y} {w}x{h}',str(E/(sys.argv[2]+'.png'))],check=True)
 subprocess.run(['grim','-g','0,0 1280x28',str(E/(sys.argv[2]+'-bar.png'))],check=True)
elif cmd=='validate-templates':
 a=(E/'active.png').read_bytes();b=(E/'inactive.png').read_bytes()
 assert a[:8]==b[:8]==b'\x89PNG\r\n\x1a\n' and a[16:24]==b[16:24] and a!=b,'Active/inactive PNG templates identical or invalid; stop before timed trials'
 save('template-validation',{'same_dimensions':True,'distinct_png_files':True,'method':'Early PNG identity guard; decoded pixel validation is performed by the host analyzer','requires_visual_review':True})
elif cmd=='native-status':
 found=[]
 for p in pathlib.Path('/proc').glob('[0-9]*'):
  try:
   if (p/'exe').resolve()==R/'midscene-wayland-capture':found.append(int(p.name))
  except OSError:pass
 print(json.dumps({'capture_pids':found}))
elif cmd=='probe-mode':
 tag,mode=sys.argv[2:4];assert tag.replace('-','').isalnum() and mode in ['discovery','plain','passive','feedback','pixels']
 subprocess.run(['quickshell','kill','-p','/usr/share/omarchy/shell','--any-display'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 for _ in range(100):
  if not any(p['comm'] in ['qs','quickshell'] for p in processes()):break
  time.sleep(.05)
 else:raise SystemExit('Old shell did not stop')
 d=E/('probe-'+tag);d.mkdir(exist_ok=True)
 env=dict(os.environ);env['QT_QPA_PLATFORM']='wayland';env['QS_DISABLE_FILE_WATCHER']='1';env['QS_NO_RELOAD_POPUP']='1'
 env['OMARCHY_STARTUP_BACKGROUND']=str((pathlib.Path.home()/'.local/state/omarchy/current/background').resolve())
 env.pop('LD_PRELOAD',None);env.pop('WAYLAND_DEBUG',None)
 if mode in ['discovery','feedback']:env['WAYLAND_DEBUG']='client'
 if mode in ['passive','feedback','pixels']:
  env['LD_PRELOAD']=str(R/'presentation-probe.so');env['MIDSCENE_PRESENT_DIR']=str(d);env['MIDSCENE_PRESENT_MODE']=mode
 child=subprocess.Popen(['quickshell','-n','-p','/usr/share/omarchy/shell'],env=env,stdout=subprocess.DEVNULL,stderr=open(d/'stderr.log','w'),start_new_session=True)
 for _ in range(100):
  if child.poll() is not None:raise SystemExit('Observed shell exited')
  try:
   run('omarchy-shell','shell','ping');break
  except subprocess.CalledProcessError:time.sleep(.1)
 else:raise SystemExit('Observed shell did not become ready')
 save('probe-mode-'+tag,{'mode':mode,'pid':child.pid,'time_ns':time.monotonic_ns(),'snapshot':snap()});print(json.dumps({'pid':child.pid,'mode':mode}))
elif cmd=='probe-health':
 tag=sys.argv[2];assert tag in ['discovery','plain','passive','feedback','pixels']
 state=json.loads((E/('probe-mode-'+tag+'.json')).read_text());pid=state['pid']
 assert any(p['pid']==pid and p['comm'] in ['qs','quickshell'] for p in processes()),'Observed shell exited after IPC startup'
 d=E/('probe-'+tag);p=d/'events.jsonl';events=[json.loads(x) for x in p.read_text().splitlines() if x.startswith('{')] if p.exists() else []
 assert not [x for x in events if x['event']=='fatal'],'Observer fatal: '+str([x for x in events if x['event']=='fatal'])
 if tag in ['passive','feedback','pixels']:assert any(x['event']=='swap-end' and x['ok'] for x in events),'Observer has not captured a successful real EGL swap'
 monitors=json.loads(run('hyprctl','-j','monitors'));assert len(monitors)==1 and monitors[0]['reserved'][1]>=26,'Real top bar is not reserving its expected area'
 print(json.dumps({'pid':pid,'mode':tag,'healthy':True}))
elif cmd=='probe-freeze':
 subprocess.run(['quickshell','kill','-p','/usr/share/omarchy/shell','--any-display'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 for _ in range(100):
  if not any(p['comm'] in ['qs','quickshell'] for p in processes()):break
  time.sleep(.05)
 else:raise SystemExit('Observed shell remained during archive freeze')
elif cmd=='probe-events':
 tag=sys.argv[2];assert tag.replace('-','').isalnum();p=E/('probe-'+tag)/'events.jsonl';print(p.read_text() if p.exists() else '')
elif cmd=='probe-pixels':
 import base64
 tag=sys.argv[2];assert tag.replace('-','').isalnum();d=E/('probe-'+tag);print(json.dumps({p.name:base64.b64encode(p.read_bytes()).decode() for p in d.glob('pixel-*.png')}))
elif cmd=='probe-discovery':
 tag=sys.argv[2] if len(sys.argv)>2 else 'discovery';assert tag in ['discovery','feedback'];d=E/('probe-'+tag);p=d/'stderr.log';lines=p.read_text(errors='replace').splitlines();keep=[x for x in lines if ('wp_presentation' in x or 'wl_surface' in x and ('commit(' in x or 'attach(' in x))]
 save('presentation-'+tag,{'source':'real shell client protocol debug; observer feedback injected only in feedback mode','wp_presentation_lines':[x for x in lines if 'wp_presentation' in x],'surface_commit_count':sum('wl_surface' in x and 'commit(' in x for x in lines),'all_log_lines':len(lines)})
 (d/'protocol-filtered.log').write_text('\n'.join(keep)+'\n');print(json.dumps({'kept_lines':len(keep),'lines':keep}))
elif cmd=='clock-check':
 os.execv(str(R/'clock-check'),[str(R/'clock-check')])
elif cmd in ['native-source','native-region']:
 fd=os.open(E/'native-capture-errors.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600);os.dup2(fd,2);os.close(fd)
 filter_mode=sys.argv[2] if len(sys.argv)>2 else 'none'
 assert filter_mode in ['none','adaptive']
 os.execv(str(R/'midscene-wayland-capture'),[str(R/'midscene-wayland-capture'),'--verify-monotonic','--trace','--png-filter',filter_mode]+(['--region','0,0,1280,28'] if cmd=='native-region' else []))
elif cmd=='input-start':
 subprocess.Popen(['python3',str(R/'input-events.py'),sys.argv[2]],stdout=subprocess.DEVNULL,stderr=open(E/'input-error.log','a'),start_new_session=True)
elif cmd=='input-end':
 d=E/sys.argv[2];(d/'stop').touch()
 for _ in range(100):
  if (d/'done').exists():break
  time.sleep(.02)
 print((d/'input.json').read_text())
elif cmd=='capture':
 # Harness grants only input-read permission inside the disposable VM.
 subprocess.Popen(['python3',str(R/'capture.py'),*sys.argv[2:]],stdout=subprocess.DEVNULL,stderr=open(E/'capture-error.log','a'),start_new_session=True)
elif cmd=='ready':
 assert (E/sys.argv[2]/'ready').exists(),'Capture not ready (check disposable input permissions)'
elif cmd=='restore':
 before=snap();save('before-restore',before)
 # GUI restore is checked before this emergency/full cleanup. Then restore bytes.
 subprocess.run(['systemctl','--user','stop','omarchy-fcitx5.service'],check=True)
 dst=pathlib.Path.home()/'.config/fcitx5';shutil.rmtree(dst);shutil.copytree(R/'fcitx5-backup',dst,symlinks=True)
 subprocess.run(['systemctl','--user','start','omarchy-fcitx5.service'],check=True)
 def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
 save('restore',{'config_byte_identical':hashes(dst)==hashes(R/'fcitx5-backup'),'service_restarted_only_during_cleanup':True})
 c=target_window();subprocess.run(['hyprctl','dispatch','hl.dsp.window.close({ window = "address:'+c['address']+'" })'],check=False)
else:raise SystemExit('Unknown operation')
