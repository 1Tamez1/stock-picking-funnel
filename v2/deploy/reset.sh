#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${DEPLOY_DIR}/.." && pwd)"
ENV_FILE="${1:-${DEPLOY_DIR}/.env.hosted}"
PROJECT_NAME="${FUNNEL_V2_STACK_NAME:-funnel-v2-hosted}"
HOSTED_HOST_HEADER="$(awk -F= '$1 == "FUNNEL_V2_HOSTNAME" {sub(/^[^=]*=/, "", $0); print $0}' "${ENV_FILE}" | tail -n 1)"
HOSTED_BASE_URL="${FUNNEL_V2_HOSTED_BASE_URL:-http://127.0.0.1}"
COMPOSE=(docker compose --project-name "${PROJECT_NAME}" --env-file "${ENV_FILE}" -f "${DEPLOY_DIR}/docker-compose.yml")

"${DEPLOY_DIR}/down.sh" "${ENV_FILE}" -v
"${DEPLOY_DIR}/up.sh" "${ENV_FILE}"

"${COMPOSE[@]}" exec -T api sh -lc "cd /app && export FUNNEL_V2_HOSTED_BASE_URL=http://caddy && export FUNNEL_V2_HOSTED_HOST_HEADER='${HOSTED_HOST_HEADER}' && /app/v2/scripts/rehearse_cutover.sh"

python3 "${ROOT_DIR}/scripts/run_hosted_validation.py" \
  --base-url "${HOSTED_BASE_URL}" \
  --host-header "${HOSTED_HOST_HEADER}"
