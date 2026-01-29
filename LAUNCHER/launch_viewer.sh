#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/csoneira/BIBLIOGRAPHY"
URL="http://localhost:8000/VIEWER/viewer.html"

cd "$ROOT"

if ! pgrep -f "CODE/viewer_server.py" >/dev/null; then
  python3 CODE/viewer_server.py >/dev/null 2>&1 &
  sleep 0.5
fi

xdg-open "$URL" >/dev/null 2>&1 &
