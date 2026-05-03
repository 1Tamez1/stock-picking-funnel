#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${ROOT_DIR}/scripts/prepare_playwright_runtime.py" >/dev/null

ENV_FILE="${ROOT_DIR}/.tmp/playwright-runtime/playwright.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Failed to prepare Playwright runtime." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

export FUNNEL_V2_API_HOST="${FUNNEL_V2_API_HOST:-127.0.0.1}"
export FUNNEL_V2_API_PORT="${FUNNEL_V2_API_PORT:-8212}"

exec "${ROOT_DIR}/scripts/run_api.sh"
