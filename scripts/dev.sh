#!/usr/bin/env bash
# Start API (8400) + Vite UI (5173). Run from repo root or ui/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_PID=""
cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if ! curl -sf --connect-timeout 1 http://127.0.0.1:8400/api/runs >/dev/null 2>&1; then
  echo "Starting API on http://127.0.0.1:8400 ..."
  uv run smart-automator-api &
  API_PID=$!
  for _ in $(seq 1 30); do
    if curl -sf --connect-timeout 1 http://127.0.0.1:8400/api/runs >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
  if ! curl -sf --connect-timeout 1 http://127.0.0.1:8400/api/runs >/dev/null 2>&1; then
    echo "API failed to start on port 8400" >&2
    exit 1
  fi
else
  echo "API already running on http://127.0.0.1:8400"
fi

cd "$ROOT/ui"
exec npm run dev
