#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <backup-directory> [manifest-path]" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$1"
MANIFEST_PATH="${2:-${ROOT_DIR}/contracts/cutback-manifest.json}"
STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

"${ROOT_DIR}/scripts/restore_hosted_state.sh" "${BACKUP_DIR}"

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_cutover_state.py" set \
  --phase "cutback" \
  --status-value "complete" \
  --reason "automatic_cutback" \
  --message "Hosted cutback completed. SQLite is the active rollback authority." \
  --source "cutback_hosted_state.sh" \
  --linked-manifest-path "${MANIFEST_PATH}" >/dev/null

mkdir -p "$(dirname "${MANIFEST_PATH}")"
cat >"${MANIFEST_PATH}" <<EOF
{
  "created_at": "${STAMP}",
  "backup_dir": "${BACKUP_DIR}",
  "rollback_authority": "sqlite",
  "status": "cutback-complete"
}
EOF

echo "Hosted cutback completed from ${BACKUP_DIR}"
