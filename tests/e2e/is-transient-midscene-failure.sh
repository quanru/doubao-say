#!/bin/bash
set -euo pipefail

if (($# != 1)); then
  echo "Usage: $0 <midscene-log>" >&2
  exit 2
fi

if grep -Eq \
  'Connection error|ETIMEDOUT|ECONNRESET|EAI_AGAIN|UND_ERR_CONNECT_TIMEOUT|failed to call AI model service' \
  "$1"; then
  exit 0
fi

# These messages identify malformed model output before an action is executed.
# Similar text from a product assertion or a valid but rejected action must fail
# immediately instead of rerunning the complete project.
grep -Eq \
  'XML parse error: Invalid parameters for action|Failed to parse action-param-json' \
  "$1"
