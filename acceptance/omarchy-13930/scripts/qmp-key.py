"""Send a real virtual-keyboard chord to an explicitly supplied disposable QEMU socket.
Example: python3 qmp-key.py /tmp/test-vm.qmp ctrl spc --disposable-vm
Host timestamps are diagnostic only, not proof of guest presentation latency.
"""
import argparse,socket,json,time
p=argparse.ArgumentParser(description=__doc__);p.add_argument('socket');p.add_argument('keys',nargs='+');p.add_argument('--disposable-vm',action='store_true',required=True);p.add_argument('--hold-ms',type=int,default=80);a=p.parse_args();assert 1<=a.hold_ms<=200
s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect(a.socket);f=s.makefile('rwb')
def read():
 line=f.readline()
 if not line:raise RuntimeError('QMP disconnected')
 return json.loads(line)
def execute(name,args=None):
 f.write((json.dumps({'execute':name,'arguments':args or {}})+'\n').encode());f.flush()
 while True:
  r=read()
  if 'error' in r:raise RuntimeError(r['error'].get('class','QMP error'))
  if 'return' in r:return r
try:
 if 'QMP' not in read():raise RuntimeError('Not a QMP endpoint')
 execute('qmp_capabilities')
 t0=time.monotonic_ns();execute('send-key',{'keys':[{'type':'qcode','data':k} for k in a.keys],'hold-time':a.hold_ms});t1=time.monotonic_ns()
 # Let QEMU release this chord before a following helper sends another one.
 time.sleep(.12)
 print(json.dumps({'keys':a.keys,'hold_ms':a.hold_ms,'host_send_start_ns':t0,'host_ack_ns':t1,'timing_valid_for_500ms':False}))
finally:f.close();s.close()
