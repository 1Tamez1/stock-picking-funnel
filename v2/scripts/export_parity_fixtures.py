from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
CONTRACT_DIR = ROOT / "contracts" / "fixtures"

if str(V1_ROOT) not in sys.path:
    sys.path.insert(0, str(V1_ROOT))

from funnel_app import db as legacy_db


def export_schema_inventory(conn: sqlite3.Connection) -> dict[str, object]:
    tables = {}
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
    for row in rows:
        name = str(row["name"])
        columns = conn.execute(f"PRAGMA table_info({name})").fetchall()
        tables[name] = [
            {
                "name": column["name"],
                "type": column["type"],
                "notnull": bool(column["notnull"]),
                "pk": bool(column["pk"]),
            }
            for column in columns
        ]
    return tables


def export_sample_payloads(conn: sqlite3.Connection) -> dict[str, object]:
    report_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM reports ORDER BY id LIMIT 12").fetchall()]
    company_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM companies ORDER BY id LIMIT 12").fetchall()]
    return {
        "bootstrap": {
            "dashboard": legacy_db.dashboard(conn),
            "settings_summary": legacy_db.settings_summary(conn),
            "stages": legacy_db.list_stages(conn),
            "buckets": legacy_db.BUCKETS,
            "report_actions": legacy_db.REPORT_ACTIONS,
        },
        "templates": legacy_db.list_templates(conn),
        "companies": {str(company_id): legacy_db.get_company(conn, company_id) for company_id in company_ids},
        "reports": {str(report_id): legacy_db.get_report(conn, report_id) for report_id in report_ids},
    }


def first_report_for_stage(conn: sqlite3.Connection, stage_id: int) -> dict[str, object] | None:
    row = conn.execute("SELECT id FROM reports WHERE stage_id = ? ORDER BY completed_at DESC, id DESC LIMIT 1", (stage_id,)).fetchone()
    if not row:
        return None
    return legacy_db.get_report(conn, int(row["id"]))


def first_report_for_result(conn: sqlite3.Connection, result: str) -> dict[str, object] | None:
    row = conn.execute("SELECT id FROM reports WHERE result = ? ORDER BY completed_at DESC, id DESC LIMIT 1", (result,)).fetchone()
    if not row:
        return None
    return legacy_db.get_report(conn, int(row["id"]))


def first_document_for_status(conn: sqlite3.Connection, status: str) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT id FROM documents WHERE normalized_status = ? ORDER BY normalized_updated_at DESC, uploaded_at DESC, id DESC LIMIT 1",
        (status,),
    ).fetchone()
    if not row:
        return None
    return legacy_db.get_document(conn, int(row["id"]))


def first_source_for_state(conn: sqlite3.Connection, state: str) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT id FROM report_sources WHERE capture_state = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
        (state,),
    ).fetchone()
    if not row:
        return None
    return legacy_db.get_report_source(conn, int(row["id"]))


def export_reference_samples(conn: sqlite3.Connection) -> dict[str, object]:
    stage_reports = {
        stage["key"]: first_report_for_stage(conn, int(stage["id"]))
        for stage in legacy_db.list_stages(conn)
    }
    result_reports = {
        result: first_report_for_result(conn, result)
        for result in ["Draft", "Proceed to Next Step", "Watchlist", "Archive"]
    }
    documents_by_status = {
        status: first_document_for_status(conn, status)
        for status in ["pending", "ready", "limited", "failed"]
    }
    sources_by_state = {
        state: first_source_for_state(conn, state)
        for state in ["pending", "ready", "limited", "failed", "link_only"]
    }
    templates = legacy_db.list_templates(conn)
    return {
        "reports_by_stage": stage_reports,
        "reports_by_result": result_reports,
        "documents_by_status": documents_by_status,
        "sources_by_capture_state": sources_by_state,
        "templates_by_stage": {item["stage_key"]: item for item in templates},
        "monitoring_rules": legacy_db.list_monitoring_rules(conn),
    }


def main() -> None:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    conn = legacy_db.connect(V1_ROOT / "var" / "funnel.db")
    try:
        fixtures = {
            "schema_inventory": export_schema_inventory(conn),
            "payloads": export_sample_payloads(conn),
            "reference_samples": export_reference_samples(conn),
        }
    finally:
        conn.close()
    (CONTRACT_DIR / "v1-parity-fixtures.json").write_text(json.dumps(fixtures, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
