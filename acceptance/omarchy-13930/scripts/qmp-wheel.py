"""Real discrete QMP wheel injection, NOT high-resolution touchpad simulation."""
import argparse,socket,json,time
p=argparse.ArgumentParser();p.add_argument('socket');p.add_argument('direction',choices=['up','down','left','right','schema','move']);p.add_argument('--x',type=int);p.add_argument('--y',type=int);p.add_argument('--disposable-vm',action='store_true',required=True);a=p.parse_args()
s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect(a.socket);f=s.makefile('rwb')
def execute(name,args=None):
    f.write((json.dumps({'execute':name,'arguments':args or {}})+'\n').encode());f.flush()
    while True:
        r=json.loads(f.readline())
        if 'error' in r: raise RuntimeError(r['error'])
        if 'return' in r:return r['return']
try:
    greeting=json.loads(f.readline());assert 'QMP' in greeting;execute('qmp_capabilities')
    if a.direction=='schema':print(json.dumps({'greeting':greeting,'schema':execute('query-qmp-schema'),'mice':execute('query-mice')}))
    elif a.direction=='move':
        assert 0<=a.x<1280 and 0<=a.y<800
        execute('input-send-event',{'events':[{'type':'abs','data':{'axis':'x','value':round(a.x*32767/1279)}},{'type':'abs','data':{'axis':'y','value':round(a.y*32767/799)}}]})
    else:
        for down in [True,False]:execute('input-send-event',{'events':[{'type':'btn','data':{'down':down,'button':'wheel-'+a.direction}}]});time.sleep(.05)
        print(json.dumps({'direction':a.direction,'transport':'QMP discrete wheel','acknowledged':True,'guest_delivery_proven':False}))
finally:f.close();s.close()
