#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${FUNNEL_V2_BACKUP_ROOT:-${ROOT_DIR}/contracts/hosted-backups}/${STAMP}"
mkdir -p "${OUT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

: "${FUNNEL_V2_POSTGRES_URL:?Set FUNNEL_V2_POSTGRES_URL to back up PostgreSQL.}"

pg_dump "${FUNNEL_V2_POSTGRES_URL}" --format=custom --file="${OUT_DIR}/postgres.dump"

if [[ -n "${FUNNEL_V2_UPLOAD_DIR:-}" && -d "${FUNNEL_V2_UPLOAD_DIR}" ]]; then
  tar -C "${FUNNEL_V2_UPLOAD_DIR}" -czf "${OUT_DIR}/uploads.tar.gz" .
fi

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/migrate_uploads_to_storage.py" \
  --manifest-only \
  --manifest-path "${OUT_DIR}/storage-manifest.json" >/dev/null

cat >"${OUT_DIR}/backup-manifest.json" <<EOF
{
  "created_at": "${STAMP}",
  "postgres_dump": "postgres.dump",
  "uploads_archive": "$( [[ -f "${OUT_DIR}/uploads.tar.gz" ]] && echo uploads.tar.gz || echo "" )",
  "storage_manifest": "storage-manifest.json"
}
EOF

echo "Hosted backup written to ${OUT_DIR}"
