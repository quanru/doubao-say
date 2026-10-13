"""Guest-local evdev + grim time brackets. Captures real pixels, never draws UI."""
import sys,pathlib,os,fcntl,struct,select,time,json,subprocess,hashlib
trial=sys.argv[1];assert trial.isalnum();x,y,w,h=map(int,sys.argv[2:6]);assert 0<=x<1280 and 0<=y<800 and 4<=w<=256 and 4<=h<=100
out=pathlib.Path('/tmp/pr15184/evidence')/trial;out.mkdir(exist_ok=False)
fds=[]
for p in pathlib.Path('/dev/input').glob('event*'):
 try:
  fd=os.open(p,os.O_RDONLY|os.O_NONBLOCK)
  fcntl.ioctl(fd,0x400445a0,struct.pack('i',time.CLOCK_MONOTONIC));fds.append(fd)
 except OSError:
  try:os.close(fd)
  except (NameError,OSError):pass
if not fds:raise SystemExit('No evdev devices with monotonic clock')
events=[];frames=[];fmt='llHHI';size=struct.calcsize(fmt)
deadline=time.monotonic()+3
try:
 while time.monotonic()<deadline:
  for fd in select.select(fds,[],[],0)[0]:
   try:data=os.read(fd,size*128)
   except BlockingIOError:continue
   for off in range(0,len(data),size):
    sec,usec,kind,code,value=struct.unpack(fmt,data[off:off+size])
    if kind==1 and code==42:events.append({'ns':sec*1000000000+usec*1000,'code':code,'value':value})
  path=out/f'{len(frames):04}.png';a=time.monotonic_ns()
  subprocess.run(['grim','-g',f'{x},{y} {w}x{h}',str(path)],check=True,timeout=2)
  b=time.monotonic_ns();frames.append({'file':path.name,'lo_ns':a,'hi_ns':b,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
  if len(frames)==1:(out/'ready').touch()
finally:
 for fd in fds:os.close(fd)
 (out/'capture.json').write_text(json.dumps({'events':events,'frames':frames,'clock':'CLOCK_MONOTONIC','input_clock_precision_ns':1000,'presentation_limit':'grim capture brackets; pixel equality against stable templates'},indent=2))
 (out/'done').touch()
