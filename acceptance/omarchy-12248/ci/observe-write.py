"""Read-only guest observer. Real grim frames in tmpfs, unchanged product timing."""
import pathlib,os,sys,time,json,subprocess,hashlib,shutil,traceback
label=sys.argv[1]
assert label in ['baseline','baseline-reopen','head','head-reopen']
r=pathlib.Path('/dev/shm/pr12248-observer')/label;r.mkdir(parents=True,exist_ok=False)
(r/'ready').touch();frames=[];samples=[];seen_read=False;write_start=None;read_frame=False;seen_write=False;error=None

def workers():
 out=[]
 for p in pathlib.Path('/proc').glob('[0-9]*'):
  try:
   args=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode()
   if not args.startswith('dd ') or 'disk-speedtest-' not in args:continue
   fields=(p/'stat').read_text().rsplit(')',1)[1].split()
   out.append({'pid':int(p.name),'ppid':int(fields[1]),'start_ticks':fields[19],'cmd':args})
  except (OSError,UnicodeError):pass
 return {'monotonic_ns':time.monotonic_ns(),'epoch_ns':time.time_ns(),'workers':out}

def kinds(s):
 return {('read' if 'iflag=direct' in p['cmd'] else 'write' if 'oflag=direct' in p['cmd'] else 'prepare') for p in s['workers']}

def capture(name,full=False):
 before=workers();start=time.monotonic_ns();epoch=time.time_ns()
 cmd=['grim']+([] if full else ['-g','350,250 580x320'])+[str(r/(name+'.png'))]
 subprocess.run(cmd,check=True,timeout=3,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 end=time.monotonic_ns();after=workers()
 frames.append({'name':name,'path':name+'.png','full_screen':full,'capture_start_ns':start,'capture_end_ns':end,'capture_epoch_ns':epoch,'before':before,'after':after,'sha256':hashlib.sha256((r/(name+'.png')).read_bytes()).hexdigest()})

try:
 deadline=time.monotonic()+90;next_frame=0
 while time.monotonic()<deadline:
  s=workers();samples.append(s);ks=kinds(s)
  if 'read' in ks:
   seen_read=True
   if not read_frame:
    capture('read-live',True);read_frame=True
  if seen_read and 'write' in ks and 'read' not in ks:
   seen_write=True
   if write_start is None:
    write_start=time.monotonic();next_frame=write_start
    capture('write-live-first',True)
   now=time.monotonic()
   if now-write_start<3 and now>=next_frame:
    capture('write-roi-'+str(len(frames)).zfill(3));next_frame=now+.25
   if now-write_start>=1.5 and not any(f['name']=='write-live-sampled' for f in frames):
    capture('write-live-sampled',True)
  if seen_write and not s['workers']:
   time.sleep(.3);capture('completed',True);break
  time.sleep(.04)
 else:raise RuntimeError('Native observer deadline exceeded')
 valid=[f for f in frames if f['name'].startswith('write-') and all(len(t['workers'])==4 and kinds(t)=={'write'} for t in [f['before'],f['after']])]
 assert len(valid)>=6,'Insufficient genuine write-active capture brackets'
 assert max(f['capture_end_ns'] for f in valid)-min(f['capture_start_ns'] for f in valid)>=1_000_000_000,'Write frame coverage too short'
 assert any(f['name']=='write-live-sampled' for f in valid),'No full native sampled-write frame with four writers both before and after'
except Exception:
 error=traceback.format_exc()
finally:
 result={'label':label,'method':'Guest-local /proc observation plus real grim captures; no stdout interception, no product changes, no phase override','tmpfs':True,'roi':'350,250 580x320','frames':frames,'samples':samples,'error':error,'status':'FAILED' if error else 'CAPTURE_BRACKETS_VERIFIED_VISUAL_REVIEW_REQUIRED'}
 (r/'observation.json').write_text(json.dumps(result,indent=2))
 # Copy only once the benchmark is no longer being observed. Preserve memory originals too.
 shutil.copytree(r,pathlib.Path('/tmp/pr12248/evidence/native-write')/label,dirs_exist_ok=True)
 (pathlib.Path('/tmp/pr12248/evidence/native-write')/label/'done').touch();(r/'done').touch()
 sys.exit(1 if error else 0)
