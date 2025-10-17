#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE="$REPO_ROOT/.env.local"

if [[ ! -f "$ENV_FILE" ]]; then
  cat <<'EOF' >&2
Missing .env.local file in repository root.
Create one with the following variables:

ZOTERO_API_KEY=your_api_key
ZOTERO_LIBRARY_ID=your_library_id
# Optional, defaults to "user"
ZOTERO_LIBRARY_TYPE=user
EOF
  exit 1
fi

set -o allexport
source "$ENV_FILE"
set +o allexport

: "${ZOTERO_API_KEY:?ZOTERO_API_KEY must be set in .env.local}"
: "${ZOTERO_LIBRARY_ID:?ZOTERO_LIBRARY_ID must be set in .env.local}"
ZOTERO_LIBRARY_TYPE=${ZOTERO_LIBRARY_TYPE:-user}
MCP_PORT=${MCP_PORT:-9180}

# Support detached mode via env or -d flag
DETACH_FLAG=""
if [[ "${DETACH:-}" == "1" ]]; then
  DETACH_FLAG="-d"
fi
if [[ "${1:-}" == "-d" ]]; then
  DETACH_FLAG="-d"
  shift
fi

# Build image if it doesn't exist
if ! docker image inspect zotero-mcp:local >/dev/null 2>&1; then
  echo "Image zotero-mcp:local not found. Building..." >&2
  docker build -t zotero-mcp:local "$REPO_ROOT"
fi

exec docker run --rm $DETACH_FLAG \
  --name zotero-mcp-sse \
  -p "$MCP_PORT:8000" \
  -e ZOTERO_API_KEY="$ZOTERO_API_KEY" \
  -e ZOTERO_LIBRARY_ID="$ZOTERO_LIBRARY_ID" \
  -e ZOTERO_LIBRARY_TYPE="$ZOTERO_LIBRARY_TYPE" \
  zotero-mcp:local \
  --transport sse "$@"
