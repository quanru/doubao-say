#!/bin/bash
set -euo pipefail
mkdir -p review-artifacts
status=0
if [[ -f work/session-state ]]; then
  bash ci/guest.sh restore > /dev/null 2>&1 || status=1
  mapfile -t state < work/session-state
  ssh -i "${state[0]}" -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR omarchy@127.0.0.1 \
    'tar -C /tmp/pr15184/evidence -cf - .' | tar -C review-artifacts/guest -xf - || status=1
  kill "${state[2]}" 2>/dev/null || true
fi
# Native HTML retains embedded screenshots. External screenshots are kept if emitted.
python3 - <<'PY'
from pathlib import Path
import shutil,json,hashlib,re
out=Path('review-artifacts');native=out/'midscene';native.mkdir(exist_ok=True)
source=Path('work/ui/midscene_run/report')
if source.exists():
 for p in source.rglob('*'):
  if p.is_file() and p.suffix in ['.html','.png','.jpg','.jpeg','.webp']:
   dest=native/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
# Fail closed before artifact upload if common credential patterns occur.
for p in out.rglob('*'):
 if p.is_file() and p.suffix in ['.html','.json','.jsonl','.txt','.log']:
  s=p.read_text(errors='ignore')
  if re.search(r'(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----|Bearer [A-Za-z0-9_.-]{24,})',s):
   shutil.rmtree(out);out.mkdir();(out/'REDACTION-BLOCK.txt').write_text('Artifact export blocked by credential-pattern scan. No evidence published.');raise SystemExit(1)
PY
python3 ci/analyze-captures.py || status=1
python3 - <<'PY'
from pathlib import Path
import hashlib,json,html
r=Path('review-artifacts');files=[p for p in r.rglob('*') if p.is_file()]
(r/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(r))+'\n' for p in sorted(files)))
ui=(r/'ui-results.json').read_text() if (r/'ui-results.json').exists() else 'UI 未执行'
lat=(r/'latency-results.json').read_text() if (r/'latency-results.json').exists() else '计时未执行'
(r/'REVIEW.html').write_text('<!doctype html><meta charset="utf-8"><title>待审阅 Omarchy 验收</title><h1>自动采集结果，待逐帧审阅</h1><p>不确定/缺少样本不能判通过。关闭 Pages；附件可见性取决于仓库。</p><h2>真实 UI</h2><pre>'+html.escape(ui)+'</pre><h2>计时区间</h2><pre>'+html.escape(lat)+'</pre>')
PY
exit "$status"
