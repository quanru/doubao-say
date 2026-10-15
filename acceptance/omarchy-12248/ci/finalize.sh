#!/bin/bash
set -euo pipefail
mkdir -p review-artifacts/guest
status=0
if [[ -f work/session-state ]]; then
 bash ci/guest.sh restore > work/restore.log 2>&1 || status=1
 cp work/restore.log review-artifacts/restore.log
 mapfile -t state < work/session-state
 ssh -i "${state[0]}" -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR omarchy@127.0.0.1 'tar -C /tmp/pr12248/evidence -cf - .' | tar -C review-artifacts/guest -xf - || status=1
 kill "${state[2]}" 2>/dev/null || true
else
 status=1
fi
export ACCEPTANCE_RESTORE_EXIT="$status"
python3 - <<'PY'
from pathlib import Path
import shutil,json,hashlib,os
r=Path('review-artifacts');s=Path('work/ui/midscene_run/report')
if s.exists():shutil.copytree(s,r/'midscene',dirs_exist_ok=True)
(r/'execution.json').write_text(json.dumps({'run_id':os.environ.get('GITHUB_RUN_ID'),'harness_commit':os.environ.get('GITHUB_SHA'),'job_status_before_restore':os.environ.get('JOB_STATUS'),'restore_exit_code':int(os.environ['ACCEPTANCE_RESTORE_EXIT']),'final_ci_status_authority':'GitHub completed run and every required step; this file is not a final CI verdict','image_picker':'SEE_RESULTS_NO_PASS_IF_MISSING','visual_review':'PENDING','model_calls':0},indent=2))
(r/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(r))+'\n' for p in sorted(r.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
PY
exit "$status"
