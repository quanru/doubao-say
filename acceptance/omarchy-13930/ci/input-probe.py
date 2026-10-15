"""Bounded Linux uinput mouse + independent evdev observation in disposable guest."""
import os,sys,socket,json,struct,fcntl,time,pathlib,select
R=pathlib.Path('/tmp/pr13930');E=R/'evidence';SOCK=R/'input-probe.sock'
assert os.geteuid()==0,'Guest root only; launched by disposable harness'
event=struct.Struct('llHHi');fds={};records=[];active=False;ui=None
def refresh():
    for p in pathlib.Path('/dev/input').glob('event*'):
        if str(p) in fds.values():continue
        try:fds[os.open(p,os.O_RDONLY|os.O_NONBLOCK)]=str(p)
        except OSError:pass
def drain(wait=0):
    ready,_,_=select.select(list(fds),[],[],wait)
    for fd in ready:
        try:data=os.read(fd,event.size*256)
        except OSError:continue
        for offset in range(0,len(data),event.size):
            sec,usec,typ,code,value=event.unpack_from(data,offset)
            if active and (typ in (0,2) or typ==1 and 272<=code<=279):records.append({'device':fds[fd],'sec':sec,'usec':usec,'type':typ,'code':code,'value':value})
def inventory():
    result=[]
    for fd,path in fds.items():
        b=bytearray(256)
        try:fcntl.ioctl(fd,0x81004506,b,True);name=bytes(b).split(b'\0')[0].decode(errors='replace')
        except OSError:name='unknown'
        p=pathlib.Path('/sys/class/input')/pathlib.Path(path).name/'device/capabilities/rel'
        result.append({'path':path,'name':name,'rel_bits':p.read_text().strip() if p.exists() else None})
    return result
def create():
    global ui
    assert ui is None
    ui=os.open('/dev/uinput',os.O_WRONLY|os.O_NONBLOCK)
    for typ in [1,2]:fcntl.ioctl(ui,0x40045564,typ)
    for code in [272,273,274]:fcntl.ioctl(ui,0x40045565,code)
    for code in [0,1,6,8]:fcntl.ioctl(ui,0x40045566,code)
    os.write(ui,struct.pack('80sHHHHi',b'Omarchy13930 horizontal test mouse',3,0x1234,0x1393,1,0)+bytes(64*4*4))
    fcntl.ioctl(ui,0x5501);time.sleep(1);refresh()
    assert any('Omarchy13930' in x['name'] for x in inventory()),'uinput evdev device absent'
def send(code,value):
    assert ui is not None and code==6 and value in [-1,1]
    os.write(ui,event.pack(0,0,2,code,value));os.write(ui,event.pack(0,0,0,0,0))
try:
    if SOCK.exists():SOCK.unlink()
    server=socket.socket(socket.AF_UNIX);server.bind(str(SOCK));SOCK.chmod(0o600);os.chown(SOCK,1000,1000);server.listen(1);server.settimeout(.1)
    refresh();deadline=time.monotonic()+800
    while time.monotonic()<deadline:
        drain()
        try:conn,_=server.accept()
        except socket.timeout:continue
        with conn:
            req=json.loads(conn.recv(4096));cmd=req['cmd']
            try:
                if cmd=='start':
                    active=False;drain();records=[];active=True;result={'devices':inventory()}
                elif cmd=='end':
                    until=time.monotonic()+.4
                    while time.monotonic()<until:drain(.05)
                    active=False;result={'events':records,'devices':inventory()}
                elif cmd=='create':create();result={'devices':inventory()}
                elif cmd=='horizontal':send(6,req['value']);result={'sent_rel_hwheel':req['value']}
                elif cmd=='stop':conn.sendall(b'{"stopped":true}');break
                else:raise RuntimeError('Unknown command')
                conn.sendall(json.dumps(result).encode())
            except Exception as e:conn.sendall(json.dumps({'error':str(e)}).encode())
finally:
    if ui is not None:fcntl.ioctl(ui,0x5502);os.close(ui)
    for fd in fds:os.close(fd)
    if SOCK.exists():SOCK.unlink()
