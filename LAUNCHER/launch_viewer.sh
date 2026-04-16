#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
URL="http://localhost:8000/VIEWER/viewer.html?open_ts=$(date +%s)"

cd "$ROOT"

if ! pgrep -f "CODE/viewer_server.py" >/dev/null; then
  python3 CODE/viewer_server.py >/dev/null 2>&1 &
  sleep 0.5
fi

xdg-open "$URL" >/dev/null 2>&1 &
