"""Read official historical package metadata only. Never install or execute packages."""
import urllib.request,tarfile,io,json,pathlib,hashlib
out=pathlib.Path('review-artifacts/versions');out.mkdir(parents=True,exist_ok=True)
url='https://archive.archlinux.org/repos/2026/10/01/extra/os/x86_64/extra.db'
result={'source':url,'purpose':'Assess coherent pre-Qt-6.12 runtime; metadata only, NO packages installed'}
try:
    with urllib.request.urlopen(url,timeout=60) as response: data=response.read(40*1024*1024)
    result['database_sha256']=hashlib.sha256(data).hexdigest();packages=[]
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:*') as tar:
        for item in tar:
            if not item.name.endswith('/desc'):continue
            text=tar.extractfile(item).read().decode();parts=text.split('\n\n');fields={}
            for part in parts:
                lines=part.strip().splitlines()
                if lines and lines[0].startswith('%'):fields[lines[0].strip('%')]=lines[1:]
            name=fields.get('NAME',[''])[0]
            if name.startswith('qt6-') or name in ['quickshell','hyprland','icu','ffmpeg','qt6-base','qt6-declarative']:packages.append(fields)
    result['packages']=packages
except Exception as e: result['error']=str(e)
(out/'historical-runtime-inventory.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'runtime_inventory':str(out/'historical-runtime-inventory.json'),'packages':len(result.get('packages',[])),'error':result.get('error')}))
