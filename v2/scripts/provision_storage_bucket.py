from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"

for candidate in (str(API_ROOT), str(ROOT.parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.storage import StorageAdapter


def main() -> None:
    settings = load_settings()
    storage = StorageAdapter(settings)
    if storage.mode != "s3_compatible":
        print("Storage bucket provisioning skipped: legacy_local mode.")
        return
    if not settings.storage_bucket:
        raise SystemExit("Set FUNNEL_V2_STORAGE_BUCKET before provisioning hosted storage.")
    client = storage._s3_client()
    assert client is not None
    bucket = settings.storage_bucket
    try:
        client.head_bucket(Bucket=bucket)
        print(f"Bucket already available: {bucket}")
        return
    except Exception:
        pass
    kwargs = {"Bucket": bucket}
    if settings.storage_region and settings.storage_region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.storage_region}
    client.create_bucket(**kwargs)
    print(f"Provisioned bucket: {bucket}")


if __name__ == "__main__":
    main()
