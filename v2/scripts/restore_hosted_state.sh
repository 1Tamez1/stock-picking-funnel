#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup-directory>" >&2
  exit 1
fi

BACKUP_DIR="$1"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

: "${FUNNEL_V2_POSTGRES_URL:?Set FUNNEL_V2_POSTGRES_URL to restore PostgreSQL.}"

pg_restore --clean --if-exists --no-owner --dbname="${FUNNEL_V2_POSTGRES_URL}" "${BACKUP_DIR}/postgres.dump"

if [[ -n "${FUNNEL_V2_UPLOAD_DIR:-}" && -f "${BACKUP_DIR}/uploads.tar.gz" ]]; then
  mkdir -p "${FUNNEL_V2_UPLOAD_DIR}"
  tar -C "${FUNNEL_V2_UPLOAD_DIR}" -xzf "${BACKUP_DIR}/uploads.tar.gz"
fi

if [[ "${FUNNEL_V2_STORAGE_MODE:-legacy_local}" == "s3_compatible" ]]; then
  "${PYTHON_BIN}" \
    "${ROOT_DIR}/scripts/migrate_uploads_to_storage.py" \
    --manifest-path "${BACKUP_DIR}/storage-restore-manifest.json" >/dev/null
fi

echo "Hosted restore completed from ${BACKUP_DIR}"
