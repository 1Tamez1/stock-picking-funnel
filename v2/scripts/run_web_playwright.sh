#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${ROOT_DIR}/web"

export FUNNEL_V2_API_PROXY_TARGET="${FUNNEL_V2_API_PROXY_TARGET:-http://127.0.0.1:8212}"

exec npm run dev -- --hostname 127.0.0.1 --port 3000
