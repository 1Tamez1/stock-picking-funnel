#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: validate.sh [env-file]

Boot the hosted Docker stack, verify owner browser/token access, run the hosted
smoke and deep validation flows, and emit a machine-readable validation bundle
under v2/contracts/hosted-runtime/live-stack-validations/.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${DEPLOY_DIR}/.." && pwd)"
ENV_FILE="${1:-${DEPLOY_DIR}/.env.hosted}"
STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${ROOT_DIR}/contracts/hosted-runtime/live-stack-validations/${STAMP}"
MANIFEST_PATH="${OUT_DIR}/validation-manifest.json"
FAILURE_REPORT_PATH="${OUT_DIR}/failure-report.json"
UP_MANIFEST_CAPTURE="${OUT_DIR}/up-manifest.json"

mkdir -p "${OUT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

read_env() {
  local key="$1"
  awk -F= -v key="${key}" '$1 == key {sub(/^[^=]*=/, "", $0); print $0}' "${ENV_FILE}" | tail -n 1
}

write_failure_report() {
  local stage="$1"
  local detail="$2"
  local artifact_link="$3"
  python3 - <<PY
import json
from pathlib import Path

payload = {
    "created_at": __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "service": "hosted_validation_runner",
    "failing_route": "",
    "failing_flow": ${stage@Q},
    "reason": "live_stack_validation_failed",
    "detail": ${detail@Q},
    "fallback_or_cutback_action": "validation_aborted",
    "parity_artifact_link": ${artifact_link@Q},
}
path = Path(${FAILURE_REPORT_PATH@Q})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

run_step() {
  local stage="$1"
  shift
  local output_path="${OUT_DIR}/${stage}.json"
  if ! "$@" >"${output_path}" 2>&1; then
    write_failure_report "${stage}" "Command failed while running ${stage}." "${output_path}"
    cat "${output_path}" >&2 || true
    exit 1
  fi
}

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

OWNER_EMAIL="$(read_env FUNNEL_V2_OWNER_EMAIL)"
OWNER_PASSWORD="$(read_env FUNNEL_V2_OWNER_PASSWORD)"

FUNNEL_V2_ISSUE_OWNER_TOKEN=1 "${DEPLOY_DIR}/up.sh" "${ENV_FILE}" > "${UP_MANIFEST_CAPTURE}"

readarray -t MANIFEST_FIELDS < <(python3 - <<PY
import json
from pathlib import Path

payload = json.loads(Path(${UP_MANIFEST_CAPTURE@Q}).read_text(encoding="utf-8"))
print(payload.get("probe_base_url", ""))
print(payload.get("host_header", ""))
print(payload.get("public_origin", ""))
print(payload.get("token", ""))
print(payload.get("owner_email", ""))
PY
)

BASE_URL="${MANIFEST_FIELDS[0]}"
HOST_HEADER="${MANIFEST_FIELDS[1]}"
PUBLIC_ORIGIN="${MANIFEST_FIELDS[2]}"
TOKEN_VALUE="${MANIFEST_FIELDS[3]}"
OWNER_EMAIL_FROM_MANIFEST="${MANIFEST_FIELDS[4]}"

if [[ -n "${OWNER_EMAIL_FROM_MANIFEST}" ]]; then
  OWNER_EMAIL="${OWNER_EMAIL_FROM_MANIFEST}"
fi

if [[ -z "${BASE_URL}" ]]; then
  write_failure_report "stack_boot" "Missing probe base URL from hosted stack manifest." "${UP_MANIFEST_CAPTURE}"
  exit 1
fi

if [[ -z "${TOKEN_VALUE}" ]]; then
  write_failure_report "token_issue" "Hosted stack boot completed, but no owner bearer token was issued." "${UP_MANIFEST_CAPTURE}"
  exit 1
fi

run_step "integrity-repair" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/repair_integrity.py" \
  --apply \
  --manifest-path "${OUT_DIR}/integrity-repair.json"

run_step "integrity-audit" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/audit_integrity.py" \
  --manifest-path "${OUT_DIR}/integrity-audit.json"

run_step "token-verification" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/verify_owner_token.py" \
  --base-url "${BASE_URL}" \
  --host-header "${HOST_HEADER}" \
  --api-token "${TOKEN_VALUE}"

if [[ -n "${OWNER_EMAIL}" && -n "${OWNER_PASSWORD}" ]]; then
  run_step "session-smoke" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_smoke.py" \
    --base-url "${BASE_URL}" \
    --host-header "${HOST_HEADER}" \
    --email "${OWNER_EMAIL}" \
    --password "${OWNER_PASSWORD}"

  run_step "session-validation" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_validation.py" \
    --base-url "${BASE_URL}" \
    --host-header "${HOST_HEADER}" \
    --email "${OWNER_EMAIL}" \
    --password "${OWNER_PASSWORD}" \
    --artifact-dir "${OUT_DIR}/session-validation" \
    --require-postgres-primary
fi

run_step "token-smoke" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_smoke.py" \
  --base-url "${BASE_URL}" \
  --host-header "${HOST_HEADER}" \
  --api-token "${TOKEN_VALUE}"

run_step "token-validation" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_hosted_validation.py" \
  --base-url "${BASE_URL}" \
  --host-header "${HOST_HEADER}" \
  --api-token "${TOKEN_VALUE}" \
  --artifact-dir "${OUT_DIR}/token-validation" \
  --require-postgres-primary

PLAYWRIGHT_STATUS="skipped"
PLAYWRIGHT_ARTIFACT=""
if [[ "${FUNNEL_V2_RUN_LIVE_PLAYWRIGHT:-0}" == "1" ]]; then
  PLAYWRIGHT_ARTIFACT="${OUT_DIR}/playwright-live.txt"
  if [[ -n "${OWNER_EMAIL}" && -n "${OWNER_PASSWORD}" ]]; then
    if (
      cd "${ROOT_DIR}/web" && \
      PLAYWRIGHT_NO_WEBSERVER=1 \
      PLAYWRIGHT_LIVE_HOSTED=1 \
      PLAYWRIGHT_BASE_URL="${PUBLIC_ORIGIN:-${BASE_URL}}" \
      PLAYWRIGHT_OWNER_EMAIL="${OWNER_EMAIL}" \
      PLAYWRIGHT_OWNER_PASSWORD="${OWNER_PASSWORD}" \
      npm run test:e2e -- --grep "live hosted stack"
    ) >"${PLAYWRIGHT_ARTIFACT}" 2>&1; then
      PLAYWRIGHT_STATUS="passed"
    else
      PLAYWRIGHT_STATUS="failed"
      write_failure_report "playwright-live" "Live hosted Playwright validation failed." "${PLAYWRIGHT_ARTIFACT}"
      cat "${PLAYWRIGHT_ARTIFACT}" >&2 || true
      exit 1
    fi
  else
    PLAYWRIGHT_STATUS="skipped_missing_owner_credentials"
  fi
fi

python3 - <<PY
import json
from pathlib import Path

manifest = {
    "created_at": __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "base_url": ${BASE_URL@Q},
    "public_origin": ${PUBLIC_ORIGIN@Q},
    "host_header": ${HOST_HEADER@Q},
    "owner_email": ${OWNER_EMAIL@Q},
    "artifacts": {
        "up_manifest": ${UP_MANIFEST_CAPTURE@Q},
        "integrity_repair": str(Path(${OUT_DIR@Q}) / "integrity-repair.json"),
        "integrity_audit": str(Path(${OUT_DIR@Q}) / "integrity-audit.json"),
        "token_verification": str(Path(${OUT_DIR@Q}) / "token-verification.json"),
        "session_smoke": str(Path(${OUT_DIR@Q}) / "session-smoke.json"),
        "session_validation": str(Path(${OUT_DIR@Q}) / "session-validation.json"),
        "token_smoke": str(Path(${OUT_DIR@Q}) / "token-smoke.json"),
        "token_validation": str(Path(${OUT_DIR@Q}) / "token-validation.json"),
        "playwright_live": ${PLAYWRIGHT_ARTIFACT@Q},
    },
    "playwright_live_status": ${PLAYWRIGHT_STATUS@Q},
    "token_issued": bool(${TOKEN_VALUE@Q}),
}
Path(${MANIFEST_PATH@Q}).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest, indent=2))
PY
