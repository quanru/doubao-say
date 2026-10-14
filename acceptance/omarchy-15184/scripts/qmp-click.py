"""Click a real virtual tablet in the explicitly selected disposable QEMU VM."""
import argparse,socket,json,time
p=argparse.ArgumentParser(description=__doc__);p.add_argument('socket');p.add_argument('x',type=int);p.add_argument('y',type=int);p.add_argument('--disposable-vm',action='store_true',required=True);a=p.parse_args()
assert 0<=a.x<1280 and 0<=a.y<800
s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect(a.socket);f=s.makefile('rwb')
def execute(name,args=None):
 f.write((json.dumps({'execute':name,'arguments':args or {}})+'\n').encode());f.flush()
 while True:
  r=json.loads(f.readline())
  if 'error' in r:raise RuntimeError(r['error'])
  if 'return' in r:return
try:
 assert 'QMP' in json.loads(f.readline());execute('qmp_capabilities')
 execute('input-send-event',{'events':[{'type':'abs','data':{'axis':'x','value':round(a.x*32767/1279)}},{'type':'abs','data':{'axis':'y','value':round(a.y*32767/799)}}]})
 execute('input-send-event',{'events':[{'type':'btn','data':{'down':True,'button':'left'}}]});time.sleep(.08)
 execute('input-send-event',{'events':[{'type':'btn','data':{'down':False,'button':'left'}}]})
 print(json.dumps({'x':a.x,'y':a.y,'device':'QMP virtual tablet'}))
finally:f.close();s.close()
