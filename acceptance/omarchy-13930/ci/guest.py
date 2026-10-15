import sys, subprocess, pathlib, json, time, hashlib, shutil, base64, socket
R = pathlib.Path('/tmp/pr13930'); E = R/'evidence'
D = pathlib.Path('/usr/share/omarchy/shell/Ui/Dropdown.qml')
G = pathlib.Path('/usr/share/omarchy/shell/plugins/dev-gallery/GalleryPanel.qml')
def run(*args): return subprocess.check_output(args, text=True).strip()
def save(name, obj): (E/(name+'.json')).write_text(json.dumps(obj, indent=2))
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def stop():
    for _ in range(5):
        p = subprocess.run(['quickshell','kill','-p','/usr/share/omarchy/shell','--any-display'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if p.returncode: break
def launch(tag):
    stop()
    launchfile=R/'launch.sh'
    launchfile.write_text('#!/bin/bash\nexport QS_DISABLE_FILE_WATCHER=1 QS_NO_RELOAD_POPUP=1\nexec quickshell -n -p /usr/share/omarchy/shell > /tmp/pr13930/evidence/'+tag+'.log 2>&1\n')
    launchfile.chmod(0o700)
    run('hyprctl','dispatch','hl.dsp.exec_cmd("/tmp/pr13930/launch.sh")')
    for _ in range(100):
        p=subprocess.run(['omarchy-shell','shell','ping'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if p.returncode==0: break
        time.sleep(.2)
    else: raise RuntimeError('Shell did not start')
    run('omarchy-shell','idle','disable')
    run('omarchy','dev','ui-preview','dropdown')
    time.sleep(2)
cmd=sys.argv[1]
if cmd=='bootstrap':
    E.mkdir(exist_ok=True)
    assert digest(D)==digest(R/"expected-head.qml"), "Installed production component differs from pinned head"
    shutil.copy(D,R/'candidate.qml'); shutil.copy(G,R/'gallery.qml')
    save('original-hashes',{'dropdown':digest(D),'gallery':digest(G)})
    save('environment',{'monitors':json.loads(run('hyprctl','-j','monitors')),'packages':run('pacman','-Q'),'graphics':run('hyprctl','systeminfo')})
    # Read-only observation of the REAL gallery component, never change its behavior.
    s=G.read_text().replace("import qs.Commons\n", "import qs.Commons\nimport qs.Commons as AcceptanceCommons\n"); needle='  id: root\n'; assert s.count(needle)==1
    observer='''
  Timer {
    interval: 100; running: true; repeat: true
    onTriggered: {
      if (!window.visible) return
      var p = demoDropdown.mapToItem(null,0, demoDropdown.height - demoDropdown.rowHeight)
      var win = demoDropdown.Window.window
      var focused = win ? win.activeFocusItem : null
      var chain = [], cur = focused
      for (var i = 0; cur && i < 12; ++i) { chain.push(String(cur)); cur = cur.parent }
      var probe = {}
      try { probe = {unqualified:String(Color), qualified:String(AcceptanceCommons.Color), unqualifiedPalette:!!Color.popups, qualifiedPalette:!!AcceptanceCommons.Color.popups} } catch (err) { probe = {error:String(err)} }
      console.log("PR13930_STATE " + JSON.stringify({colorProbe:probe, activeFocusItem:String(focused), focusChain:chain, windowActive:win ? win.active : false, keyCatcherFocus:keyCatcher.activeFocus, keyCatcherBlocked:keyCatcher.blocked, pointerHover:acceptanceTriggerHover.hovered, coordinateSpace:"window-content-logical", value: demoDropdown.value, popup: demoDropdown.popupOpen, x:p.x, y:p.y, width:demoDropdown.width, height:demoDropdown.rowHeight, row:demoDropdown.popupRowHeight, time:Date.now()}))
    }
  }
'''
    marker='                  id: demoDropdown\n'
    assert s.count(marker)==1
    s=s.replace(marker,marker+'                  HoverHandler { id: acceptanceTriggerHover }\n')
    G.write_text(s.replace(needle,needle+observer))
    save('instrumentation',{'scope':'gallery-only read-only Timer, real Dropdown untouched','gallery_original':digest(R/'gallery.qml'),'gallery_observed':digest(G)})
elif cmd=='mode':
    mode=sys.argv[2]; assert mode in ['baseline','candidate']
    stop(); shutil.copy(R/(mode+'.qml'),D)
    assert digest(D)==digest(R/(mode+'.qml'))
    tag=sys.argv[3] if len(sys.argv)>3 else mode;assert tag.replace('-','').isalnum()
    save(tag+'-source',{'installed_dropdown_sha256':digest(D),'gallery_sha256':digest(G)})
    (R/'mode').write_text(tag); launch(tag)
elif cmd=='state':
    mode=(R/'mode').read_text(); lines=(E/(mode+'.log')).read_text(errors='replace').splitlines()
    for line in reversed(lines):
        if 'PR13930_STATE ' in line:
            data=json.loads(line.split('PR13930_STATE ',1)[1]); assert abs(time.time()*1000-data['time'])<3000,'stale observation';print(json.dumps(data));break
    else: raise RuntimeError('No actual gallery observation')
elif cmd=='probe':
    request={'cmd':sys.argv[2]}
    if len(sys.argv)>3:request['value']=int(sys.argv[3])
    client=socket.socket(socket.AF_UNIX);client.settimeout(10);client.connect(str(R/'input-probe.sock'))
    client.sendall(json.dumps(request).encode());data=b''
    while chunk:=client.recv(65536):data+=chunk
    obj=json.loads(data);assert 'error' not in obj,obj;print(json.dumps(obj))
elif cmd=='geometry':
    clients=json.loads(run('hyprctl','-j','clients'))
    matches=[c for c in clients if c.get('title')=='Omarchy shell – dev gallery' and c.get('mapped')]
    assert len(matches)==1,'Expected one gallery window'
    c=matches[0];monitors=json.loads(run('hyprctl','-j','monitors'))
    assert len(monitors)==1,'Multi-monitor QMP mapping not validated'
    m=monitors[0];assert m['transform']==0 and m['width']==1280 and m['height']==800
    assert c['monitor']==m['id'] and not c['xwayland']
    print(json.dumps({'client':{k:c[k] for k in ['address','at','size','monitor','title']},'monitor':{k:m[k] for k in ['id','x','y','width','height','scale','transform']}}))
elif cmd=='focus-gallery':
    clients=json.loads(run('hyprctl','-j','clients'));c=[c for c in clients if c.get('title')=='Omarchy shell – dev gallery' and c.get('mapped')];assert len(c)==1
    run('hyprctl','dispatch','hl.dsp.focus({ window = "address:'+c[0]['address']+'" })')
    assert json.loads(run('hyprctl','-j','activewindow'))['address']==c[0]['address']
elif cmd=='runtime-state':
    before={'packages':run('pacman','-Q'),'dropdown':digest(D),'gallery':digest(G)}
    save('matched-runtime',before);print(json.dumps(before))
elif cmd=='stop':
    stop()
elif cmd=='desktop-state':
    name=sys.argv[2]; assert name.replace('-','').isalnum()
    save(name+'-desktop', {k:json.loads(run('hyprctl','-j',k)) for k in ['activewindow','clients','devices','layers']})
elif cmd=='screenshot':
    name=sys.argv[2]; assert name.replace('-','').isalnum()
    run('grim',str(E/(name+'.png')))
elif cmd=='restore':
    if (R/'input-probe.sock').exists():
        client=socket.socket(socket.AF_UNIX);client.settimeout(5);client.connect(str(R/'input-probe.sock'));client.sendall(b'{"cmd":"stop"}');client.recv(4096);client.close()
        for _ in range(50):
            if not (R/'input-probe.sock').exists():break
            time.sleep(.1)
        assert not (R/'input-probe.sock').exists(),'Input probe leaked'
    for _ in range(50):
        if not any('Omarchy13930' in p.read_text(errors='replace') for p in pathlib.Path('/sys/class/input').glob('event*/device/name')):break
        time.sleep(.1)
    save('input-cleanup',{'socket_removed':not (R/'input-probe.sock').exists(),'test_device_present':any('Omarchy13930' in p.read_text(errors='replace') for p in pathlib.Path('/sys/class/input').glob('event*/device/name'))})
    assert not json.loads((E/'input-cleanup.json').read_text())['test_device_present']
    stop(); shutil.copy(R/'candidate.qml',D);shutil.copy(R/'gallery.qml',G)
    result={'dropdown':digest(D),'gallery':digest(G)}
    assert result==json.loads((E/'original-hashes.json').read_text())
    save('restored-hashes',result)
    run('omarchy-restart-shell')
else: raise RuntimeError('Unknown operation')
