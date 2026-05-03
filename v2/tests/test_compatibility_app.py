from __future__ import annotations

import sys
import sqlite3
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


class CompatibilityApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_health_returns_minimal_liveness_and_headers(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["status"], "ok")
        self.assertNotIn("db_path", response.json())
        self.assertIn("X-Funnel-Instance-Id", response.headers)
        self.assertIn("X-Funnel-Request-Id", response.headers)

    def test_bootstrap_returns_dashboard_shape(self) -> None:
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("dashboard", payload)
        self.assertIn("stages", payload)
        self.assertIn("buckets", payload)
        self.assertIn("report_actions", payload)

    def test_report_endpoint_returns_agent_contract_when_reports_exist(self) -> None:
        conn = sqlite3.connect(V1_ROOT / "var" / "funnel.db")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT id FROM reports ORDER BY id LIMIT 1").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        report_id = int(row["id"])

        response = self.client.get(f"/api/reports/{report_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["report"]
        self.assertIn("template", payload)
        self.assertIn("completion", payload)
        self.assertIn("workflow", payload)
        self.assertIn("sources", payload)
        self.assertIn("company_sources", payload)
        self.assertIn("agent_contract", payload)


if __name__ == "__main__":
    unittest.main()
