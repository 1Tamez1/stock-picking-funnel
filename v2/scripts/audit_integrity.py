from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
WORKSPACE_ROOT = ROOT.parent

if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.append(str(WORKSPACE_ROOT))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.config import load_settings
from app.integrity import audit_connection
from app.shadow import ShadowBackend
from app.postgres_services import PostgresCompatibilityStore
from funnel_app import db as legacy_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit template/report integrity for zero-loss hosted promotion.")
    parser.add_argument(
        "--manifest-path",
        default=os.environ.get("FUNNEL_V2_INTEGRITY_MANIFEST", "").strip(),
        help="Optional output path for the integrity manifest.",
    )
    parser.add_argument(
        "--include-postgres-view",
        action="store_true",
        default=os.environ.get("FUNNEL_V2_INCLUDE_POSTGRES_INTEGRITY", "1").strip().lower() in {"1", "true", "yes", "on"},
        help="Also audit the PostgreSQL-backed legacy view generated from the current V2 shadow store.",
    )
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        default=False,
        help="Return a non-zero exit code when any warnings are present, not just critical issues.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def dataset_summary(payload: dict[str, Any], *, role: str, blocking: bool) -> dict[str, Any]:
    return {
        **payload,
        "role": role,
        "blocking": blocking,
    }


def main() -> None:
    args = parse_args()
    settings = load_settings()
    manifest_path = (
        Path(args.manifest_path).expanduser().resolve()
        if args.manifest_path
        else (settings.contract_dir / "integrity" / "integrity-audit.json")
    )

    results: list[dict[str, Any]] = []
    sqlite_blocking = not args.include_postgres_view
    conn = legacy_db.connect(settings.sqlite_path)
    try:
        results.append(
            dataset_summary(
                audit_connection(conn, dataset_label="sqlite_source"),
                role="rollback_source",
                blocking=sqlite_blocking,
            )
        )
    finally:
        conn.close()

    if args.include_postgres_view:
        shadow = ShadowBackend(settings)
        try:
            store = PostgresCompatibilityStore(shadow)
            if shadow.enabled:
                store.ensure_synced(force=False)
            else:
                shadow.ensure_schema()
                shadow.sync_from_sqlite_snapshot(settings.sqlite_path, settings.upload_root, "integrity-audit-bootstrap")
            with store.open_legacy_view() as pg_conn:
                results.append(
                    dataset_summary(
                        audit_connection(pg_conn, dataset_label="postgres_legacy_view"),
                        role="authoritative_candidate",
                        blocking=True,
                    )
                )
        finally:
            shadow.close()

    blocking_results = [item for item in results if item.get("blocking")]
    source_results = [item for item in results if item.get("role") == "rollback_source"]
    totals = {
        "datasets": len(results),
        "templates": sum(int(item.get("templates", 0)) for item in results),
        "reports": sum(int(item.get("reports", 0)) for item in results),
        "issue_count": sum(int(item.get("issue_count", 0)) for item in results),
        "critical_issue_count": sum(int(item.get("critical_issue_count", 0)) for item in blocking_results),
        "blocking_dataset_count": len(blocking_results),
        "blocking_issue_count": sum(int(item.get("issue_count", 0)) for item in blocking_results),
        "source_issue_count": sum(int(item.get("issue_count", 0)) for item in source_results),
        "source_critical_issue_count": sum(int(item.get("critical_issue_count", 0)) for item in source_results),
    }
    payload = {
        "created_at": utc_now(),
        "sqlite_path": str(settings.sqlite_path),
        "upload_root": str(settings.upload_root),
        "backend_mode": settings.backend_mode,
        "storage_mode": settings.storage_mode,
        "totals": totals,
        "datasets": results,
    }
    write_json(manifest_path, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    if totals["critical_issue_count"] > 0:
        raise SystemExit(1)
    if args.fail_on_warnings and totals["blocking_issue_count"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
