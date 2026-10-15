import pathlib,subprocess,shutil,json,hashlib,re,os,signal
R=pathlib.Path('review-artifacts');R.mkdir(exist_ok=True);failed=False
state=pathlib.Path('work/session-state')
if state.exists():
    key,socket,pid,run_dir=state.read_text().splitlines()
    ssh=['ssh','-i',key,'-p','2222','-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-o','LogLevel=ERROR','omarchy@127.0.0.1']
    try:
        subprocess.run(['bash','ci/guest.sh','restore'],check=True,timeout=60)
        # Restore the exact owners/modes recorded BEFORE the disposable VM changes.
        entries=[]
        for line in (R/'versions/original-permissions.txt').read_text().splitlines():
            uid,gid,mode,path=line.split();assert path in ['/usr/share/omarchy/shell/Ui/Dropdown.qml','/usr/share/omarchy/shell/plugins/dev-gallery/GalleryPanel.qml'];assert uid.isdigit() and gid.isdigit() and mode.isdigit()
            entries.append((uid,gid,mode,path))
        assert len(entries)==2
        original=pathlib.Path('work/iso/bin/omarchy-iso-test').read_text()
        password=re.search(r'^GUEST_PASSWORD="([^"\n]+)"',original,re.M).group(1)
        for uid,gid,mode,path in entries:
            subprocess.run(ssh+['sudo -S chown '+uid+':'+gid+' '+path],input=password+'\n',text=True,capture_output=True,check=True,timeout=15)
            subprocess.run(ssh+['sudo -S chmod '+mode+' '+path],input=password+'\n',text=True,capture_output=True,check=True,timeout=15)
        after=subprocess.check_output(ssh+['stat -c "%u %g %a %n" '+ ' '.join(e[3] for e in entries)],text=True)
        assert after.strip()==(R/'versions/original-permissions.txt').read_text().strip()
        (R/'versions/restored-permissions.txt').write_text(after)
    except Exception as e:
        failed=True;(R/'restore-failure.json').write_text(json.dumps({'error':type(e).__name__,'detail':'Configuration restoration failed; inspect CI error stage. No credentials exported.'}))
    try:
        (R/'guest').mkdir(exist_ok=True)
        p=subprocess.run(ssh+['tar -C /tmp/pr13930/evidence -cf - .'],capture_output=True,check=True,timeout=30)
        subprocess.run(['tar','-C',str(R/'guest'),'-xf','-'],input=p.stdout,check=True)
    except Exception: failed=True
    try:os.kill(int(pid),signal.SIGTERM)
    except ProcessLookupError:pass
source=pathlib.Path('work/ui/midscene_run/report')
if source.exists(): shutil.copytree(source,R/'midscene',dirs_exist_ok=True)
restore_ok=state.exists() and not failed
required=['steps.json','coverage.json','guest/restored-hashes.json','versions/restored-permissions.txt','guest/input-cleanup.json','qmp-horizontal-actual-events.json']
missing=[x for x in required if not (R/x).is_file()]
htmls=list((R/'midscene').glob('**/*.html')) if (R/'midscene').exists() else []
if missing or not htmls:failed=True
coverage=json.loads((R/'coverage.json').read_text()) if (R/'coverage.json').exists() else {}
if not coverage.get('complete'):failed=True
(R/'completion.json').write_text(json.dumps({'restoration_succeeded':restore_ok,'missing':missing,'raw_midscene_html_count':len(htmls),'automated_suite_complete':not failed,'independent_visual_review':'PENDING','fine_touchpad':'NOT_COVERED','horizontal_guest_delivery':coverage.get('horizontal','NOT_VERIFIED'),'models':0},indent=2))
(R/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(R))+'\n' for p in sorted(R.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
raise SystemExit(1 if failed else 0)
