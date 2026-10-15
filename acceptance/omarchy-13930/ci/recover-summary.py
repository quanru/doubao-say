import pathlib,re,base64,hashlib,tarfile,io,json
s=pathlib.Path('/tmp/pr13930-existing.log').read_text()
m=re.search(r'PR13930_EVIDENCE_BEGIN (\d+) ([a-f0-9]{64})',s);assert m and 'PR13930_EVIDENCE_END' in s
d=base64.b64decode(''.join(re.findall(r'PR13930_EVIDENCE_DATA ([A-Za-z0-9+/=]+)',s)),validate=True)
assert len(d)==int(m[1]) and hashlib.sha256(d).hexdigest()==m[2]
print('ORIGINAL_ARCHIVE',len(d),m[2])
names=['failure.json','restore-failure.json','completion.json','steps.json','latest-input-mapping.json','guest/original-hashes.json','guest/restored-hashes.json','versions/original-permissions.txt','versions/restored-permissions.txt']
with tarfile.open(fileobj=io.BytesIO(d)) as tar:
    print('MEMBERS',json.dumps([x.name for x in tar.getmembers() if x.isfile()]))
    for name in names:
        try:f=tar.extractfile(name)
        except KeyError: print('MISSING',name);continue
        value=f.read().decode()
        if name=='steps.json':
            steps=json.loads(value);value=json.dumps({'count':len(steps),'last_steps':steps[-3:]})
        assert len(value)<24000,name
        print('SUMMARY_FILE',name,value)
    for name in ['guest/baseline.log','guest/candidate.log']:
        try:lines=tar.extractfile(name).read().decode(errors='replace').splitlines()
        except KeyError:continue
        errors=[line for line in lines if 'PR13930_STATE' not in line and re.search(r'Error|WARN|failed',line)]
        print('SHELL_ERRORS',name,'\n'.join(errors[-15:]))
lines=[line for line in s.splitlines() if len(line)<1500 and re.search(r'Error|Traceback|Assertion|Process completed|restore|Restore',line)]
print('LOG_ERROR_TAIL','\n'.join(lines[-30:]))
