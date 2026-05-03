from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(API_ROOT), str(V1_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.main import create_app
from funnel_app import db as legacy_db


class ReportSectionModuleTest(unittest.TestCase):
    def temp_conn(self):
        tempdir = tempfile.TemporaryDirectory(dir=ROOT / "contracts")
        db_path = Path(tempdir.name) / "funnel.db"
        shutil.copy2(V1_ROOT / "var" / "funnel.db", db_path)
        legacy_db.setup_database(db_path, auto_confirm_seed=True)
        conn = legacy_db.connect(db_path)
        return tempdir, conn

    def first_report_id(self, conn) -> int:
        row = conn.execute("SELECT id FROM reports ORDER BY id LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        return int(row["id"])

    def create_fresh_data_collection_report(self, conn) -> dict:
        company = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
        stage = conn.execute("SELECT id FROM stages WHERE key = 'data_collection'").fetchone()
        self.assertIsNotNone(company)
        self.assertIsNotNone(stage)
        return legacy_db.create_report(conn, {"company_id": int(company["id"]), "stage_id": int(stage["id"])})

    def test_section_modules_round_trip_existing_report_state(self) -> None:
        tempdir, conn = self.temp_conn()
        try:
            report_id = self.first_report_id(conn)
            report = legacy_db.get_report(conn, report_id)
            self.assertIsNotNone(report)
            self.assertEqual(len(report["section_modules"]), report["template"]["schema"]["section_count"])

            composed = legacy_db.compose_report_from_modules(conn, report_id)
            for key in (
                "responses",
                "metrics",
                "section_ratings",
                "data_quality",
                "field_sources",
                "field_notes",
                "field_exceptions",
                "watchlist_objective_rules",
                "result",
                "summary",
                "next_action",
                "review_date",
            ):
                self.assertEqual(report.get(key), composed.get(key), key)
        finally:
            conn.close()
            tempdir.cleanup()

    def test_section_patch_updates_only_section_contract_and_report_revision(self) -> None:
        tempdir, conn = self.temp_conn()
        try:
            report = self.create_fresh_data_collection_report(conn)
            report_id = int(report["id"])
            section = None
            entry = None
            for section_summary in report["section_modules"]:
                candidate = legacy_db.get_report_section(conn, report_id, section_summary["section_id"])["section"]
                editable = next((item for item in candidate["entries"] if not item["read_only"]), None)
                if editable:
                    section = candidate
                    entry = editable
                    break
            self.assertIsNotNone(section)
            self.assertIsNotNone(entry)
            if entry["kind"] == "select" and entry.get("options"):
                value = entry["options"][0]
            elif entry["kind"] == "checkbox":
                value = "true"
            elif entry["kind"] in {"metric", "number"}:
                value = "1"
            else:
                value = "modular section smoke value"

            updated = legacy_db.update_report_section(
                conn,
                report_id,
                section["section_id"],
                {
                    "expected_report_revision": report["revision"],
                    "expected_section_revision": section["section_revision"],
                    "entries": [
                        {
                            "field_id": entry["field_id"],
                            "value": value,
                            "notes": {"value": "module note"},
                        }
                    ],
                    "section_rating": 2,
                    "data_quality": 3,
                },
            )

            self.assertEqual(updated["section"]["section_revision"], section["section_revision"] + 1)
            reread = legacy_db.get_report(conn, report_id)
            self.assertEqual(reread["revision"], report["revision"] + 1)
            store = reread["metrics"] if entry["kind"] in {"metric", "number"} else reread["responses"]
            self.assertEqual(store.get(entry["field_id"]), value)
            self.assertEqual(reread["field_notes"].get(entry["field_id"]), "module note")
            self.assertEqual(reread["section_ratings"].get(section["section_id"]), 2.0)
            self.assertEqual(reread["data_quality"].get(section["section_id"]), 3.0)
        finally:
            conn.close()
            tempdir.cleanup()

    def test_mcp_lists_tools_and_reads_section_resource(self) -> None:
        client = TestClient(create_app())
        try:
            reports = client.get("/api/reports?include_drafts=1&per_page=1")
            self.assertEqual(reports.status_code, 200)
            report_id = int(reports.json()["reports"][0]["id"])
            sections = client.get(f"/api/reports/{report_id}/sections")
            self.assertEqual(sections.status_code, 200)
            section_id = sections.json()["sections"][0]["section_id"]

            tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
            self.assertEqual(tools.status_code, 200)
            self.assertIn("patch_report_section", {tool["name"] for tool in tools.json()["result"]["tools"]})

            resource = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "resources/read",
                    "params": {"uri": f"funnel://reports/{report_id}/sections/{section_id}"},
                },
            )
            self.assertEqual(resource.status_code, 200)
            content = resource.json()["result"]["contents"][0]
            self.assertEqual(content["mimeType"], "application/json")
            self.assertIn(section_id, content["text"])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
