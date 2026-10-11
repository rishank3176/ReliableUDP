#!/usr/bin/env bash
# Start the ReliableUDP API and the dashboard. Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  if [[ -x "${HOME}/.local/bin/uv" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
  else
    echo "uv was not found. On macOS install it with:"
    echo "  brew install uv"
    exit 1
  fi
fi

uv sync
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

BACK_PID=""
cleanup() {
  if [[ -n "${BACK_PID}" ]]; then
    kill "${BACK_PID}" 2>/dev/null || true
    wait "${BACK_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

uv run uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000 &
BACK_PID=$!

cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
