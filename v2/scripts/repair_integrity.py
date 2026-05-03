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

from sqlalchemy import select

from app.config import load_settings
from app.db.models import Report
from app.db.models import Stage
from app.db.models import Template
from app.integrity import diff_json
from app.postgres_services import PostgresCompatibilityStore
from app.shadow import ShadowBackend
from funnel_app import db as legacy_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair V2-side template/report integrity without mutating the source SQLite authority.")
    parser.add_argument("--apply", action="store_true", help="Apply the proposed repairs to the V2 shadow/PostgreSQL store.")
    parser.add_argument(
        "--manifest-path",
        default=os.environ.get("FUNNEL_V2_REPAIR_MANIFEST", "").strip(),
        help="Optional output path for the repair manifest.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def template_repairs(session) -> list[dict[str, Any]]:
    stage_keys = {
        int(row.id): row.key
        for row in session.execute(select(Stage.id, Stage.key)).all()
    }
    repairs: list[dict[str, Any]] = []
    for template in session.execute(select(Template).order_by(Template.id)).scalars():
        repaired_schema = legacy_db.schema_with_catalog(
            legacy_db.template_schema(str(template.markdown or "")),
            stage_key=str(stage_keys.get(int(template.stage_id), "")),
        )
        if not diff_json(template.schema_json or {}, repaired_schema):
            continue
        repairs.append(
            {
                "entity": "template",
                "id": int(template.id),
                "change": "schema_json_regenerated_from_markdown",
                "before_digest": legacy_db.dump_json(template.schema_json or {}),
                "after_digest": legacy_db.dump_json(repaired_schema),
                "apply": lambda template=template, repaired_schema=repaired_schema: setattr(template, "schema_json", repaired_schema),
            }
        )
    return repairs


def report_repairs(session, store: PostgresCompatibilityStore) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    for report in session.execute(select(Report).order_by(Report.id)).scalars():
        payload = store.raw_report(int(report.id))["report"]
        normalized = legacy_db.normalize_report_state(payload)
        stored_rules = legacy_db.stored_objective_rules(payload.get("watchlist_objective_rules") or [])
        candidates = {
            "responses_json": normalized["responses"],
            "metrics_json": normalized["metrics"],
            "section_ratings_json": normalized["section_ratings"],
            "data_quality_json": normalized["data_quality"],
            "field_sources_json": normalized["field_sources"],
            "field_notes_json": normalized["field_notes"],
            "field_exceptions_json": normalized["field_exceptions"],
            "watchlist_objective_rules_json": stored_rules,
        }
        dirty_fields: dict[str, dict[str, Any]] = {}
        for field_name, repaired_value in candidates.items():
            current_value = getattr(report, field_name) or ({} if field_name != "watchlist_objective_rules_json" else [])
            if not diff_json(current_value, repaired_value):
                continue
            dirty_fields[field_name] = {
                "before": current_value,
                "after": repaired_value,
            }
        if not dirty_fields:
            continue
        repairs.append(
            {
                "entity": "report",
                "id": int(report.id),
                "change": "normalized_payload_pruned_to_live_schema",
                "fields": {
                    field_name: {
                        "before_digest": legacy_db.dump_json(values["before"]),
                        "after_digest": legacy_db.dump_json(values["after"]),
                    }
                    for field_name, values in dirty_fields.items()
                },
                "apply": lambda report=report, dirty_fields=dirty_fields: [
                    setattr(report, field_name, values["after"]) for field_name, values in dirty_fields.items()
                ],
            }
        )
    return repairs


def scrub_callable_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        item.pop("apply", None)
        cleaned.append(item)
    return cleaned


def main() -> None:
    args = parse_args()
    settings = load_settings()
    manifest_path = (
        Path(args.manifest_path).expanduser().resolve()
        if args.manifest_path
        else (settings.contract_dir / "integrity" / "integrity-repair.json")
    )
    shadow = ShadowBackend(settings)
    try:
        store = PostgresCompatibilityStore(shadow)
        if shadow.enabled:
            store.ensure_synced(force=True)
        else:
            shadow.ensure_schema()
            shadow.sync_from_sqlite_snapshot(settings.sqlite_path, settings.upload_root, "integrity-repair-bootstrap")
        session = shadow.session_factory()()
        try:
            template_changes = template_repairs(session)
            report_changes = report_repairs(session, store)
            if args.apply:
                for entry in [*template_changes, *report_changes]:
                    entry["apply"]()
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()

        payload = {
            "created_at": utc_now(),
            "applied": bool(args.apply),
            "backend_mode": settings.backend_mode,
            "postgres_url": settings.postgres_url,
            "template_repairs": scrub_callable_entries(template_changes),
            "report_repairs": scrub_callable_entries(report_changes),
            "summary": {
                "template_repairs": len(template_changes),
                "report_repairs": len(report_changes),
                "total_repairs": len(template_changes) + len(report_changes),
            },
        }
        write_json(manifest_path, payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    finally:
        shadow.close()


if __name__ == "__main__":
    main()
