import sys, subprocess, pathlib, json, time, hashlib, shutil
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
    s=G.read_text(); needle='  id: root\n'; assert s.count(needle)==1
    observer='''
  Timer {
    interval: 100; running: true; repeat: true
    onTriggered: {
      if (!window.visible) return
      var p = demoDropdown.mapToGlobal(0, demoDropdown.height - demoDropdown.rowHeight)
      console.log("PR13930_STATE " + JSON.stringify({value: demoDropdown.value, popup: demoDropdown.popupOpen, x:p.x, y:p.y, width:demoDropdown.width, height:demoDropdown.rowHeight, row:demoDropdown.popupRowHeight, time:Date.now()}))
    }
  }
'''
    G.write_text(s.replace(needle,needle+observer))
    save('instrumentation',{'scope':'gallery-only read-only Timer, real Dropdown untouched','gallery_original':digest(R/'gallery.qml'),'gallery_observed':digest(G)})
elif cmd=='mode':
    mode=sys.argv[2]; assert mode in ['baseline','candidate']
    stop(); shutil.copy(R/(mode+'.qml'),D)
    assert digest(D)==digest(R/(mode+'.qml'))
    save(mode+'-source',{'installed_dropdown_sha256':digest(D),'gallery_sha256':digest(G)})
    (R/'mode').write_text(mode); launch(mode)
elif cmd=='state':
    mode=(R/'mode').read_text(); lines=(E/(mode+'.log')).read_text(errors='replace').splitlines()
    for line in reversed(lines):
        if 'PR13930_STATE ' in line:
            data=json.loads(line.split('PR13930_STATE ',1)[1]); assert abs(time.time()*1000-data['time'])<3000,'stale observation';print(json.dumps(data));break
    else: raise RuntimeError('No actual gallery observation')
elif cmd=='screenshot':
    name=sys.argv[2]; assert name.replace('-','').isalnum()
    run('grim',str(E/(name+'.png')))
elif cmd=='restore':
    stop(); shutil.copy(R/'candidate.qml',D);shutil.copy(R/'gallery.qml',G)
    result={'dropdown':digest(D),'gallery':digest(G)}
    assert result==json.loads((E/'original-hashes.json').read_text())
    save('restored-hashes',result)
    run('omarchy-restart-shell')
else: raise RuntimeError('Unknown operation')
