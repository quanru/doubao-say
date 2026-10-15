import socket,json,sys,pathlib
state=pathlib.Path('work/session-state').read_text().splitlines();s=socket.socket(socket.AF_UNIX);s.settimeout(10);s.connect(state[1]);f=s.makefile('rwb')
def call(n,a={}):
 f.write((json.dumps({'execute':n,'arguments':a})+'\n').encode());f.flush()
 while True:
  r=json.loads(f.readline())
  if 'error' in r:raise RuntimeError(r)
  if 'return' in r:return r['return']
json.loads(f.readline());call('qmp_capabilities');blocks=call('query-block');assert any(x['device']=='drive0' for x in blocks)
call('block_set_io_throttle',{'device':'drive0','bps':0,'bps_rd':64*1024*1024,'bps_wr':64*1024*1024,'iops':0,'iops_rd':0,'iops_wr':0})
pathlib.Path('review-artifacts/versions/throttle.json').write_text(json.dumps({'reason':'Extend genuine virtual disk staging for observation; not a disk performance benchmark','bytes_per_second_read':64*1024*1024,'bytes_per_second_write':64*1024*1024,'blocks':blocks},indent=2))
