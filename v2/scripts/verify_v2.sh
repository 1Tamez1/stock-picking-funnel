#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${ROOT_DIR}/.."
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Create the v2 virtualenv and install API dependencies first." >&2
  exit 1
fi

cd "${WORKSPACE_DIR}"

python3 "${ROOT_DIR}/scripts/backup_v1_state.py"
python3 "${ROOT_DIR}/scripts/build_parity_matrix.py"
python3 "${ROOT_DIR}/scripts/export_parity_fixtures.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/migrate_sqlite_to_postgres.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/generate_shadow_artifacts.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/repair_integrity.py" --apply
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/audit_integrity.py"
python3 "${ROOT_DIR}/scripts/compare_parity.py"
"${PYTHON_BIN}" -m unittest discover -s "${ROOT_DIR}/tests" -v

cd "${ROOT_DIR}/web"
PLAYWRIGHT_NO_WEBSERVER=1 npm run test:e2e -- --list
npm run build
