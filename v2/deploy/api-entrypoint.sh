#!/usr/bin/env sh
set -eu

cd /app

python /app/v2/scripts/wait_for_tcp.py postgres 5432 --timeout-seconds 90

if [ "${FUNNEL_V2_STORAGE_MODE:-legacy_local}" = "s3_compatible" ]; then
  python /app/v2/scripts/wait_for_tcp.py minio 9000 --timeout-seconds 90
fi

python /app/v2/scripts/migrate_postgres_schema.py
python /app/v2/scripts/provision_storage_bucket.py

if [ -n "${FUNNEL_V2_OWNER_EMAIL:-}" ] && [ -n "${FUNNEL_V2_OWNER_PASSWORD:-}" ]; then
  python /app/v2/scripts/bootstrap_owner.py \
    --email "${FUNNEL_V2_OWNER_EMAIL}" \
    --password "${FUNNEL_V2_OWNER_PASSWORD}" \
    --name "${FUNNEL_V2_OWNER_NAME:-Owner}" >/dev/null
fi

exec python -m uvicorn app.main:app --app-dir /app/v2/api --host 0.0.0.0 --port "${FUNNEL_V2_API_PORT:-8211}"
