#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Create the v2 virtualenv and install API dependencies first." >&2
  exit 1
fi

cd "${ROOT_DIR}/.."
exec "${PYTHON_BIN}" "${ROOT_DIR}/worker/run_worker.py"
