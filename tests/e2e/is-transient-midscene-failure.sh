#!/bin/bash
set -euo pipefail

if (($# != 1)); then
  echo "Usage: $0 <midscene-log>" >&2
  exit 2
fi

grep -Eq \
  'Connection error|ETIMEDOUT|ECONNRESET|EAI_AGAIN|UND_ERR_CONNECT_TIMEOUT|failed to call AI model service|XML parse error|Invalid parameters for action|Failed to parse action-param-json|No valid action generated' \
  "$1"
