from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.main import create_app
from funnel_app import db as legacy_db


class RealDbContractParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())
        cls.conn = legacy_db.connect(V1_ROOT / "var" / "funnel.db")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        cls.client.close()

    def test_bootstrap_matches_legacy_db(self) -> None:
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "dashboard": legacy_db.dashboard(self.conn),
                "settings_summary": legacy_db.settings_summary(self.conn),
                "stages": legacy_db.list_stages(self.conn),
                "buckets": legacy_db.BUCKETS,
                "report_actions": legacy_db.REPORT_ACTIONS,
            },
        )

    def test_template_library_matches_legacy_db(self) -> None:
        response = self.client.get("/api/templates")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["templates"], legacy_db.list_templates(self.conn))

    def test_monitoring_rules_match_legacy_db(self) -> None:
        response = self.client.get("/api/monitoring")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rules"], legacy_db.list_monitoring_rules(self.conn, bucket="monitoring"))

    def test_sample_companies_match_legacy_db(self) -> None:
        company_ids = [
            int(row["id"])
            for row in self.conn.execute("SELECT id FROM companies ORDER BY id LIMIT 5").fetchall()
        ]
        for company_id in company_ids:
            with self.subTest(company_id=company_id):
                response = self.client.get(f"/api/companies/{company_id}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["company"], legacy_db.get_company(self.conn, int(company_id)))

    def test_reference_stage_reports_match_legacy_db(self) -> None:
        for stage in legacy_db.list_stages(self.conn):
            row = self.conn.execute(
                "SELECT id FROM reports WHERE stage_id = ? ORDER BY completed_at DESC, id DESC LIMIT 1",
                (int(stage["id"]),),
            ).fetchone()
            if row is None:
                continue
            report_id = int(row["id"])
            with self.subTest(stage_key=stage["key"], report_id=report_id):
                response = self.client.get(f"/api/reports/{report_id}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["report"], legacy_db.get_report(self.conn, report_id))

    def test_reference_stage_reports_expose_runbook_fields(self) -> None:
        for stage in legacy_db.list_stages(self.conn):
            row = self.conn.execute(
                "SELECT id FROM reports WHERE stage_id = ? ORDER BY completed_at DESC, id DESC LIMIT 1",
                (int(stage["id"]),),
            ).fetchone()
            if row is None:
                continue
            report_id = int(row["id"])
            with self.subTest(stage_key=stage["key"], report_id=report_id):
                payload = self.client.get(f"/api/reports/{report_id}").json()["report"]
                self.assertIn("agent_contract", payload)
                self.assertIn("completion", payload)
                self.assertIn("workflow", payload)
                self.assertIn("suggested_sources", payload)
                self.assertIn("company_sources", payload)
                self.assertIsInstance(payload["agent_contract"].get("readonly_field_ids", []), list)
                self.assertIn("latest_upstream_report", payload["workflow"])


if __name__ == "__main__":
    unittest.main()
