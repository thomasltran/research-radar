#!/usr/bin/env bash
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$FRONTEND_DIR/.." && pwd)"
BACKEND_URL="http://127.0.0.1:8000"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID"
  fi
}
trap cleanup EXIT

if ! curl -s "$BACKEND_URL/api/health" >/dev/null 2>&1; then
  echo "Starting backend on ${BACKEND_URL}..."
  (cd "$ROOT_DIR" && python -m src.web_server >/tmp/research-radar-web.log 2>&1) &
  BACKEND_PID=$!
  until curl -s "$BACKEND_URL/api/health" >/dev/null 2>&1; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "Backend exited before becoming ready. See /tmp/research-radar-web.log"
      exit 1
    fi
    sleep 1
  done
fi

curl -s -X POST "$BACKEND_URL/api/workspace/relink"
