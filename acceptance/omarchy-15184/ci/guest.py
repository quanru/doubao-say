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
 for command in ['fcitx5','fcitx5-configtool','grim','hyprctl','foot']:assert shutil.which(command),command
 monitors=json.loads(run('hyprctl','-j','monitors'));assert len(monitors)==1 and monitors[0]['width']==1280 and monitors[0]['height']==800 and monitors[0]['scale']==1,'Require 1280x800 scale=1 guest for 1:1 VNC ROI'
 save('package-versions',{'packages':run('pacman','-Q'),'kernel':run('uname','-r'),'monitors':json.loads(run('hyprctl','-j','monitors'))})
 config=pathlib.Path.home()/'.config/fcitx5';shutil.copytree(config,R/'fcitx5-backup',symlinks=True)
 text=(config/'config').read_text();assert '[Hotkey/AltTriggerKeys]\n0=Shift_L' in text,'Expected real configured lone Shift trigger'
 initial=snap();assert 'pinyin' in json.dumps(initial['info']),'Pinyin must come from fresh ISO provisioning'
 assert any('/usr/share/omarchy/default/input-methods/indicator.py' in p['cmd'] for p in initial['processes']),'Candidate indicator not running'
 save('initial',initial)
 run('omarchy-shell','idle','disable')
 subprocess.Popen(['foot','--app-id=org.omarchy.pr15184','sh','-c','cat > /tmp/pr15184/committed.txt'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
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
 run('hyprctl','dispatch','focuswindow','class:^(org.omarchy.pr15184)$')
elif cmd=='committed':
 s=(R/'committed.txt').read_text();assert any('\u4e00'<=c<='\u9fff' for c in s),'No actual committed Han text'
 save('composition',{'committed':s});print(s)
elif cmd=='template':
 x,y,w,h=map(int,sys.argv[3:7]);assert 0<=x<1280 and 0<=y<800 and 4<=w<=256 and 4<=h<=100
 subprocess.run(['grim','-g',f'{x},{y} {w}x{h}',str(E/(sys.argv[2]+'.png'))],check=True)
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
 subprocess.run(['hyprctl','dispatch','closewindow','class:^(org.omarchy.pr15184)$'],check=False)
else:raise SystemExit('Unknown operation')
