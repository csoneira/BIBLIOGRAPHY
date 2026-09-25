#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LIBRARY_ROOT="$(python3 CODE/bib.py library-path)"
URL="http://localhost:8000/VIEWER/viewer.html?open_ts=$(date +%s)"
PID_FILE="${XDG_RUNTIME_DIR:-/tmp}/bibliography-viewer-${UID}.pid"
LIBRARY_FILE="${PID_FILE}.library"

cd "$ROOT"

server_is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid=$(<"$PID_FILE")
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" == "$ROOT" ]] || return 1
  [[ -f "$LIBRARY_FILE" ]] || return 1
  [[ "$(<"$LIBRARY_FILE")" == "$LIBRARY_ROOT" ]] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | rg -q "CODE/viewer_server.py"
}

start_server() {
  python3 CODE/viewer_server.py >/dev/null 2>&1 &
  echo $! >"$PID_FILE"
  echo "$LIBRARY_ROOT" >"$LIBRARY_FILE"
  sleep 0.5
}

stop_managed_server() {
  [[ -f "$PID_FILE" ]] || return 0
  local pid
  pid=$(<"$PID_FILE")
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" == "$ROOT" ]] || return 0
  if tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | rg -q "CODE/viewer_server.py"; then
    kill "$pid"
    sleep 0.2
  fi
}

if server_is_running; then
  pid=$(<"$PID_FILE")
  if [[ CODE/viewer_server.py -nt "$PID_FILE" ]]; then
    kill "$pid"
    sleep 0.2
    start_server
  fi
else
  stop_managed_server
  start_server
fi

xdg-open "$URL" >/dev/null 2>&1 &
