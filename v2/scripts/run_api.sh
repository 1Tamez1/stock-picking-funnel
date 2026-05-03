#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Create the v2 virtualenv and install API dependencies first." >&2
  exit 1
fi

cd "${ROOT_DIR}/.."

ARGS=(
  -m
  uvicorn
  app.main:app
  --app-dir
  "${ROOT_DIR}/api"
  --host
  "${FUNNEL_V2_API_HOST:-127.0.0.1}"
  --port
  "${FUNNEL_V2_API_PORT:-8211}"
)

if [[ "${FUNNEL_V2_API_RELOAD:-0}" == "1" ]]; then
  ARGS+=(--reload)
fi

exec "${PYTHON_BIN}" "${ARGS[@]}"
