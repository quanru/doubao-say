import base64, hashlib, pathlib, re
s=pathlib.Path('/tmp/existing-job.log').read_text()
begin=re.search(r'PR15184_EVIDENCE_BEGIN (\d+) ([a-f0-9]{64})',s)
assert begin and 'PR15184_EVIDENCE_END' in s
parts=re.findall(r'PR15184_EVIDENCE_DATA ([A-Za-z0-9+/=]+)',s)
data=base64.b64decode(''.join(parts),validate=True)
assert len(data)==int(begin[1]) and len(data)<=20*1024*1024
assert hashlib.sha256(data).hexdigest()==begin[2]
out=pathlib.Path('acceptance/omarchy-15184/evidence');out.mkdir(exist_ok=True)
(out/'run-38402519102.tar.gz').write_bytes(data)
(out/'run-38402519102.sha256').write_text(begin[2]+'  run-38402519102.tar.gz\n')
print('Recovered sanitized archive:',len(data),'bytes SHA256',begin[2])
for line in s.splitlines():
 if len(line)<1000 and re.search(r'Error|Assertion|Traceback|PASS|FAIL|INCONCLUSIVE|budget|cost|CNY',line):
  print(line)
