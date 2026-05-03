#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup-directory>" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$1"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

"${ROOT_DIR}/scripts/restore_hosted_state.sh" "${BACKUP_DIR}"
"${ROOT_DIR}/scripts/verify_v2.sh"

if [[ -n "${FUNNEL_V2_POSTGRES_URL:-}" && "${FUNNEL_V2_POSTGRES_URL}" != sqlite* ]]; then
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/verify_postgres_promotion.py"
fi

if [[ -n "${FUNNEL_V2_HOSTED_BASE_URL:-}" ]]; then
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_smoke.py"
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_validation.py"
fi
