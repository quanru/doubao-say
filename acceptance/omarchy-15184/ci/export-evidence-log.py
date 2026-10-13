"""Transport sanitized evidence in free CI logs; no artifact storage or Pages."""
from pathlib import Path
import io,tarfile,base64,hashlib
root=Path('review-artifacts');assert root.is_dir()
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode='w:gz') as tar:
 for p in sorted(root.rglob('*')):
  if p.is_file():
   assert p.suffix in {'.html','.png','.jpg','.jpeg','.webp','.json','.jsonl','.csv','.txt','.log','.diff'} or p.name in {'SHA256SUMS','ready','done','iso.sha256'},str(p)
   tar.add(p,arcname=str(p.relative_to(root)),recursive=False)
data=buf.getvalue()
assert len(data)<=20*1024*1024,'Evidence exceeds log transport cap; leave run logs for diagnosis'
print('PR15184_EVIDENCE_BEGIN '+str(len(data))+' '+hashlib.sha256(data).hexdigest(),flush=True)
s=base64.b64encode(data).decode()
for i in range(0,len(s),32000): print('PR15184_EVIDENCE_DATA '+s[i:i+32000],flush=True)
print('PR15184_EVIDENCE_END',flush=True)
