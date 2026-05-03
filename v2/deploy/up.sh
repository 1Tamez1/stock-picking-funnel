#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${DEPLOY_DIR}/.." && pwd)"
ENV_FILE="${1:-${DEPLOY_DIR}/.env.hosted}"
MANIFEST_DIR="${ROOT_DIR}/contracts/hosted-runtime"
MANIFEST_PATH="${MANIFEST_DIR}/up-manifest.json"
FAILURE_REPORT_PATH="${MANIFEST_DIR}/up-failure-report.json"
PROJECT_NAME="${FUNNEL_V2_STACK_NAME:-funnel-v2-hosted}"
ISSUE_TOKEN="${FUNNEL_V2_ISSUE_OWNER_TOKEN:-0}"
TOKEN_LABEL="${FUNNEL_V2_OWNER_TOKEN_LABEL:-Hosted Validation Token}"

mkdir -p "${MANIFEST_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to boot the hosted validation stack." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to probe the hosted validation stack." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to write hosted stack manifests." >&2
  exit 1
fi

read_env() {
  local key="$1"
  awk -F= -v key="${key}" '$1 == key {sub(/^[^=]*=/, "", $0); print $0}' "${ENV_FILE}" | tail -n 1
}

HOST_HEADER="$(read_env FUNNEL_V2_HOSTNAME)"
PUBLIC_ORIGIN="$(read_env FUNNEL_V2_WEB_ORIGIN)"
OWNER_EMAIL="$(read_env FUNNEL_V2_OWNER_EMAIL)"
PROBE_BASE_URL="${FUNNEL_V2_HOSTED_BASE_URL:-http://127.0.0.1}"
COMPOSE=(docker compose --project-name "${PROJECT_NAME}" --env-file "${ENV_FILE}" -f "${DEPLOY_DIR}/docker-compose.yml")

write_failure_report() {
  local service="$1"
  local detail="$2"
  local action="$3"
  python3 - <<PY
import json
from pathlib import Path

payload = {
    "created_at": __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "service": ${service@Q},
    "failing_route": "",
    "failing_flow": "stack_boot",
    "reason": "service_readiness_failed",
    "detail": ${detail@Q},
    "fallback_or_cutback_action": ${action@Q},
    "parity_artifact_link": "",
}
path = Path(${FAILURE_REPORT_PATH@Q})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

service_container_id() {
  "${COMPOSE[@]}" ps -q "$1"
}

service_status() {
  local container_id
  container_id="$(service_container_id "$1")"
  if [[ -z "${container_id}" ]]; then
    echo "missing"
    return
  fi
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}"
}

wait_for_service() {
  local service="$1"
  local expected="$2"
  local timeout_seconds="${3:-180}"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    local status
    status="$(service_status "${service}")"
    if [[ "${status}" == "${expected}" ]]; then
      return 0
    fi
    if [[ "${status}" == "unhealthy" || "${status}" == "exited" || "${status}" == "dead" || "${status}" == "missing" ]]; then
      write_failure_report "${service}" "Expected ${expected}, observed ${status}." "stack_boot_failed"
      echo "Service ${service} failed while waiting for ${expected}; current status: ${status}" >&2
      return 1
    fi
    sleep 2
  done
  write_failure_report "${service}" "Timed out waiting for ${expected}." "stack_boot_timeout"
  echo "Timed out waiting for service ${service} to reach ${expected}." >&2
  return 1
}

if ! "${COMPOSE[@]}" up -d --build; then
  write_failure_report "compose" "docker compose up failed." "stack_boot_failed"
  exit 1
fi

wait_for_service postgres healthy 180
wait_for_service minio running 120
wait_for_service api healthy 180
wait_for_service web healthy 180
wait_for_service worker running 120
wait_for_service caddy running 120

for _ in $(seq 1 90); do
  if curl -fsS -H "Host: ${HOST_HEADER}" "${PROBE_BASE_URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! curl -fsS -H "Host: ${HOST_HEADER}" "${PROBE_BASE_URL}/api/health" >/dev/null; then
  write_failure_report "api" "HTTP liveness probe failed for /api/health." "stack_boot_failed"
  exit 1
fi
if ! curl -fsS -H "Host: ${HOST_HEADER}" "${PROBE_BASE_URL}/login" >/dev/null; then
  write_failure_report "web" "HTTP readiness probe failed for /login." "stack_boot_failed"
  exit 1
fi

if ! "${COMPOSE[@]}" exec -T api sh -lc 'if [ -n "${FUNNEL_V2_OWNER_EMAIL:-}" ] && [ -n "${FUNNEL_V2_OWNER_PASSWORD:-}" ]; then python /app/v2/scripts/bootstrap_owner.py --email "${FUNNEL_V2_OWNER_EMAIL}" --password "${FUNNEL_V2_OWNER_PASSWORD}" --name "${FUNNEL_V2_OWNER_NAME:-Owner}" >/dev/null; fi'; then
  write_failure_report "api" "Owner bootstrap failed inside the API container." "stack_boot_failed"
  exit 1
fi

TOKEN_VALUE=""
TOKEN_METADATA='{}'
if [[ "${ISSUE_TOKEN}" == "1" || "${ISSUE_TOKEN}" == "true" || "${ISSUE_TOKEN}" == "yes" || "${ISSUE_TOKEN}" == "on" ]]; then
  if ! TOKEN_JSON="$("${COMPOSE[@]}" exec -T api python /app/v2/scripts/manage_owner_tokens.py issue --label "${TOKEN_LABEL}")"; then
    write_failure_report "api" "Owner bearer token issuance failed." "stack_boot_failed"
    exit 1
  fi
  TOKEN_VALUE="$(printf '%s' "${TOKEN_JSON}" | python3 -c 'import json, sys; print((json.load(sys.stdin) or {}).get("token", ""))')"
  TOKEN_METADATA="$(printf '%s' "${TOKEN_JSON}" | python3 -c 'import json, sys; print(json.dumps((json.load(sys.stdin) or {}).get("token_metadata", {})))')"
fi

python3 - <<PY
import json
from pathlib import Path

manifest = {
    "created_at": __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "stack": "${PROJECT_NAME}",
    "env_file": "${ENV_FILE}",
    "probe_base_url": "${PROBE_BASE_URL}",
    "host_header": "${HOST_HEADER}",
    "public_origin": "${PUBLIC_ORIGIN}",
    "owner_email": "${OWNER_EMAIL}",
    "token": "${TOKEN_VALUE}",
    "token_metadata": json.loads('''${TOKEN_METADATA}'''),
    "service_status": {
        "postgres": "${service_status postgres}",
        "minio": "${service_status minio}",
        "api": "${service_status api}",
        "worker": "${service_status worker}",
        "web": "${service_status web}",
        "caddy": "${service_status caddy}",
    },
    "health_urls": {
        "api_health": "${PROBE_BASE_URL}/api/health",
        "web_login": "${PROBE_BASE_URL}/login",
    },
}
Path("${MANIFEST_PATH}").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest, indent=2))
PY
