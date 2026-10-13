#!/bin/bash
set -euo pipefail
mkdir -p review-artifacts
if [[ -f work/session-state ]]; then
  bash ci/guest.sh restore > /dev/null 2>&1 || true
  mapfile -t state < work/session-state
  kill "${state[2]}" 2>/dev/null || true
fi
python3 - <<'PY'
import os,json,pathlib
r=pathlib.Path('review-artifacts/versions')
summary={'phase':'prepare-only','job_status':os.environ.get('JOB_STATUS','unknown'),'inference_calls':0,'artifact_uploads':0,'pages_deployment':False,'actual_acceptance':'NOT_EXECUTED'}
for name in ['source-pins.json','builder-image.txt','iso.sha256','remote-refs.txt']:
 p=r/name
 if p.is_file():summary[name]=p.read_text().strip()
text=json.dumps(summary,ensure_ascii=False,indent=2)
print(text)
p=pathlib.Path(os.environ['GITHUB_STEP_SUMMARY']);p.write_text('## 无模型环境预检\n\n```json\n'+text+'\n```\n\n仅环境准备，不代表两项实际验收通过。没有上传任何artifact或缓存。\n')
PY
