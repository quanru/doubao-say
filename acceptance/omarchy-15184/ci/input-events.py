"""Guest evdev input timestamps only; the pinned Midscene native source captures pixels."""
import sys,pathlib,os,fcntl,struct,select,time,json
trial=sys.argv[1];assert trial.isalnum()
out=pathlib.Path('/tmp/pr15184/evidence')/trial;out.mkdir(exist_ok=False)
fds=[];events=[];fmt='llHHI';size=struct.calcsize(fmt)
clock='linux-monotonic:'+pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
try:
 for p in pathlib.Path('/dev/input').glob('event*'):
  fd=None
  try:
   fd=os.open(p,os.O_RDONLY|os.O_NONBLOCK);fcntl.ioctl(fd,0x400445a0,struct.pack('i',time.CLOCK_MONOTONIC));fds.append(fd)
  except OSError:
   if fd is not None:os.close(fd)
 if not fds:raise RuntimeError('No readable evdev monotonic input devices')
 (out/'ready').touch();deadline=time.monotonic()+10
 while time.monotonic()<deadline and not (out/'stop').exists():
  for fd in select.select(fds,[],[],.01)[0]:
   try:data=os.read(fd,size*128)
   except BlockingIOError:continue
   for off in range(0,len(data),size):
    sec,usec,kind,code,value=struct.unpack(fmt,data[off:off+size])
    if kind==1 and code==42:events.append({'ns':sec*1000000000+usec*1000,'code':code,'value':value})
finally:
 for fd in fds:os.close(fd)
 (out/'input.json').write_text(json.dumps({'events':events,'clockId':clock,'precision_ns':1000},indent=2))
 (out/'done').touch()
