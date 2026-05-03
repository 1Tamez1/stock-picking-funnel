#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="${FUNNEL_V2_STACK_NAME:-funnel-v2-hosted}"
EXTRA_ARGS=()
ENV_FILE="${DEPLOY_DIR}/.env.hosted"

if [[ $# -gt 0 && "${1}" != -* ]]; then
  ENV_FILE="$1"
  shift
fi
EXTRA_ARGS=("$@")

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to stop the hosted validation stack." >&2
  exit 1
fi

docker compose \
  --project-name "${PROJECT_NAME}" \
  --env-file "${ENV_FILE}" \
  -f "${DEPLOY_DIR}/docker-compose.yml" \
  down --remove-orphans "${EXTRA_ARGS[@]}"
