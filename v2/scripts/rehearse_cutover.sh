#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${ROOT_DIR}/contracts/cutover-rehearsals/${STAMP}"
mkdir -p "${OUT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

BACKUP_OUTPUT="$("${ROOT_DIR}/scripts/backup_hosted_state.sh")"
BACKUP_DIR="${BACKUP_OUTPUT##* }"

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_write_freeze.py" enable \
  --reason "cutover_rehearsal" \
  --message "Writes are temporarily frozen while the hosted cutover rehearsal snapshots data and imports the live delta." \
  --source "rehearse_cutover.sh" \
  --manifest-path "${OUT_DIR}/write-freeze.json" >/dev/null

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_cutover_state.py" set \
  --phase "rehearsal" \
  --status-value "running" \
  --reason "cutover_rehearsal" \
  --message "Hosted cutover rehearsal is running. SQLite remains rollback authority until validation completes." \
  --source "rehearse_cutover.sh" \
  --linked-manifest-path "${OUT_DIR}/rehearsal-manifest.json" \
  --manifest-path "${OUT_DIR}/cutover-state-running.json" >/dev/null

cleanup() {
  local status="$1"
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_write_freeze.py" disable >/dev/null || true
  if [[ "${status}" -ne 0 ]]; then
    "${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_cutover_state.py" set \
      --phase "rehearsal" \
      --status-value "failed" \
      --cutback-required \
      --reason "cutover_rehearsal_failed" \
      --message "Hosted cutover rehearsal failed. Cutback is being applied and SQLite remains rollback authority." \
      --source "rehearse_cutover.sh" \
      --linked-manifest-path "${OUT_DIR}/rehearsal-manifest.json" \
      --manifest-path "${OUT_DIR}/cutover-state-failed.json" >/dev/null || true
    "${ROOT_DIR}/scripts/cutback_hosted_state.sh" "${BACKUP_DIR}" "${OUT_DIR}/cutback-manifest.json"
  fi
}
trap 'cleanup $?' EXIT

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/migrate_sqlite_to_postgres.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/migrate_uploads_to_storage.py" \
  --manifest-path "${OUT_DIR}/storage-migration-manifest.json"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/generate_shadow_artifacts.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/repair_integrity.py" \
  --apply \
  --manifest-path "${OUT_DIR}/integrity-repair.json" >/dev/null
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/audit_integrity.py" \
  --manifest-path "${OUT_DIR}/integrity-audit.json" >/dev/null
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/verify_postgres_promotion.py" \
  > "${OUT_DIR}/postgres-promotion.json"
python3 "${ROOT_DIR}/scripts/compare_parity.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_write_freeze.py" disable >/dev/null

if [[ -n "${FUNNEL_V2_HOSTED_BASE_URL:-}" ]]; then
  if [[ -n "${FUNNEL_V2_OWNER_EMAIL:-}" && -n "${FUNNEL_V2_OWNER_PASSWORD:-}" ]]; then
    "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_smoke.py" \
      > "${OUT_DIR}/hosted-smoke-session.json"
    "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_validation.py" \
      --artifact-dir "${OUT_DIR}/hosted-validation-session" \
      > "${OUT_DIR}/hosted-validation-session.json"
  fi

  TOKEN_JSON="$("${PYTHON_BIN}" "${ROOT_DIR}/scripts/manage_owner_tokens.py" issue --label "Cutover Rehearsal Token")"
  export FUNNEL_V2_API_TOKEN
  FUNNEL_V2_API_TOKEN="$(printf '%s' "${TOKEN_JSON}" | python3 -c 'import json, sys; print((json.load(sys.stdin) or {}).get("token", ""))')"
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/verify_owner_token.py" \
    > "${OUT_DIR}/token-verification.json"
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_smoke.py" \
    --api-token "${FUNNEL_V2_API_TOKEN}" \
    > "${OUT_DIR}/hosted-smoke-token.json"
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_validation.py" \
    --api-token "${FUNNEL_V2_API_TOKEN}" \
    --artifact-dir "${OUT_DIR}/hosted-validation-token" \
    > "${OUT_DIR}/hosted-validation-token.json"
fi

cat >"${OUT_DIR}/rehearsal-manifest.json" <<EOF
{
  "created_at": "${STAMP}",
  "backup_dir": "${BACKUP_DIR}",
  "write_freeze": "write-freeze.json",
  "storage_manifest": "storage-migration-manifest.json",
  "integrity_repair": "integrity-repair.json",
  "integrity_audit": "integrity-audit.json",
  "postgres_promotion": "postgres-promotion.json",
  "hosted_smoke_session": "$( [[ -f "${OUT_DIR}/hosted-smoke-session.json" ]] && echo hosted-smoke-session.json || echo "" )",
  "hosted_validation_session": "$( [[ -f "${OUT_DIR}/hosted-validation-session.json" ]] && echo hosted-validation-session.json || echo "" )",
  "token_verification": "$( [[ -f "${OUT_DIR}/token-verification.json" ]] && echo token-verification.json || echo "" )",
  "hosted_smoke_token": "$( [[ -f "${OUT_DIR}/hosted-smoke-token.json" ]] && echo hosted-smoke-token.json || echo "" )",
  "hosted_validation_token": "$( [[ -f "${OUT_DIR}/hosted-validation-token.json" ]] && echo hosted-validation-token.json || echo "" )"
}
EOF

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/set_cutover_state.py" set \
  --phase "rehearsal" \
  --status-value "validated" \
  --reason "cutover_rehearsal_complete" \
  --message "Hosted cutover rehearsal completed successfully. SQLite remains rollback authority until final cutover." \
  --source "rehearse_cutover.sh" \
  --linked-manifest-path "${OUT_DIR}/rehearsal-manifest.json" \
  --manifest-path "${OUT_DIR}/cutover-state-validated.json" >/dev/null

trap - EXIT
echo "Cutover rehearsal completed at ${OUT_DIR}"
