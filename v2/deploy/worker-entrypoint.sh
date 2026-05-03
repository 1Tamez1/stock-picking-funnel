#!/usr/bin/env sh
set -eu

cd /app

python /app/v2/scripts/wait_for_tcp.py postgres 5432 --timeout-seconds 90

if [ "${FUNNEL_V2_STORAGE_MODE:-legacy_local}" = "s3_compatible" ]; then
  python /app/v2/scripts/wait_for_tcp.py minio 9000 --timeout-seconds 90
fi

python /app/v2/scripts/migrate_postgres_schema.py
python /app/v2/scripts/provision_storage_bucket.py

exec python /app/v2/worker/run_worker.py
