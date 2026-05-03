from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi import Response
from sqlalchemy import select

from funnel_app import db as legacy_db


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.db.models import Template
from app.main import create_app
from app.storage import StorageResolution
from app.shadow import ShadowBackend


@contextlib.contextmanager
def temporary_env(mapping: dict[str, str]):
    original = {key: os.environ.get(key) for key in mapping}
    try:
        os.environ.update(mapping)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class PostgresPromotionTest(unittest.TestCase):
    def make_runtime(self, *, copy_sqlite: bool = True) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str], Path]:
        tempdir = tempfile.TemporaryDirectory(dir=ROOT / "contracts")
        runtime_root = Path(tempdir.name)
        sqlite_path = runtime_root / "funnel.db"
        if copy_sqlite:
            shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_path)
        else:
            sqlite_path = V1_ROOT / "var" / "funnel.db"
        env = {
            "FUNNEL_V2_BACKEND_MODE": "postgres_verify",
            "FUNNEL_V2_CONTRACT_DIR": str(runtime_root / "contracts"),
            "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(runtime_root / 'shadow.db').as_posix()}",
            "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
            "FUNNEL_V2_UPLOAD_DIR": str(V1_ROOT / "var" / "uploads"),
        }
        return tempdir, env, runtime_root

    def test_postgres_verify_promotes_templates_on_first_request(self) -> None:
        tempdir, env, runtime_root = self.make_runtime()
        try:
            with temporary_env(env):
                with TestClient(create_app()) as client:
                    response = client.get("/api/templates")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Funnel-Execution-Policy"], "postgres_primary_with_legacy_fallback")
                self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")

                summary_path = runtime_root / "contracts" / "shadow" / "promotion-summary.json"
                self.assertTrue(summary_path.exists())
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                category = summary["categories"]["templates.list"]
                self.assertGreaterEqual(category["served_by"]["postgres"], 1)
                self.assertEqual(category["fallbacks"], 0)
        finally:
            tempdir.cleanup()

    def test_postgres_verify_promotes_all_read_routes_on_first_request(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    company_id = int(conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()["id"])
                    report_id = int(conn.execute("SELECT id FROM reports ORDER BY id LIMIT 1").fetchone()["id"])
                    template_id = int(conn.execute("SELECT id FROM templates ORDER BY id LIMIT 1").fetchone()["id"])
                finally:
                    conn.close()

                routes = [
                    "/api/bootstrap",
                    "/api/stages",
                    "/api/companies",
                    f"/api/companies/{company_id}",
                    "/api/reports",
                    f"/api/reports/{report_id}",
                    "/api/templates",
                    f"/api/templates/{template_id}",
                    "/api/monitoring",
                ]
                with TestClient(create_app()) as client:
                    for route in routes:
                        with self.subTest(route=route):
                            response = client.get(route)
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                            self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")
        finally:
            tempdir.cleanup()

    def test_postgres_verify_falls_back_when_postgres_state_mismatches(self) -> None:
        tempdir, env, runtime_root = self.make_runtime()
        try:
            with temporary_env(env):
                with TestClient(create_app()) as client:
                    baseline = client.get("/api/templates")
                    self.assertEqual(baseline.status_code, 200)
                    self.assertEqual(baseline.headers["X-Funnel-Served-By"], "postgres")

                    settings = load_settings()
                    shadow = ShadowBackend(settings)
                    try:
                        session = shadow.session_factory()()
                        try:
                            template = session.execute(
                                select(Template).where(Template.is_active.is_(True)).order_by(Template.id)
                            ).scalars().first()
                            self.assertIsNotNone(template)
                            template.name = "Broken Template Name"
                            session.commit()
                        finally:
                            session.close()
                    finally:
                        shadow.close()

                    response = client.get("/api/templates")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), baseline.json())
                self.assertEqual(response.headers["X-Funnel-Served-By"], "legacy")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "1")
                mismatch_dir = runtime_root / "contracts" / "shadow" / "contract-mismatches"
                self.assertTrue(any(mismatch_dir.glob("*.json")))
                fallback_dir = runtime_root / "contracts" / "shadow" / "fallback-events"
                self.assertTrue(any(fallback_dir.glob("*.json")))
        finally:
            tempdir.cleanup()

    def test_postgres_verify_promotes_low_risk_company_write(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                with TestClient(create_app()) as client:
                    response = client.post("/api/companies", json={"ticker": "PGPRM", "name": "Promotion Test"})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.headers["X-Funnel-Execution-Policy"], "postgres_primary_with_legacy_fallback")
                self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")
                reconciliation_dir = Path(env["FUNNEL_V2_CONTRACT_DIR"]) / "shadow" / "state-reconciliations"
                self.assertTrue(any(reconciliation_dir.glob("*.json")))
        finally:
            tempdir.cleanup()

    def test_postgres_verify_promotes_low_risk_template_and_monitoring_writes(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    stage_id = int(conn.execute("SELECT id FROM stages ORDER BY sequence, id LIMIT 1").fetchone()["id"])
                    company_id = int(conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()["id"])
                finally:
                    conn.close()

                with TestClient(create_app()) as client:
                    template_response = client.post(
                        "/api/templates",
                        json={
                            "stage_id": stage_id,
                            "name": "PG Template Promotion",
                            "description": "Template promotion test.",
                            "markdown": "# Title\n\n## Section\n\n- Field: text",
                        },
                    )
                    self.assertEqual(template_response.status_code, 201)
                    self.assertEqual(template_response.headers["X-Funnel-Served-By"], "postgres")
                    self.assertEqual(template_response.headers["X-Funnel-Legacy-Fallback"], "0")

                    monitoring_response = client.post(
                        "/api/monitoring-rules",
                        json={
                            "company_id": company_id,
                            "metric_name": "Promo Test Rule",
                            "comparator": "<=",
                            "threshold_value": 10,
                            "unit": "USD",
                            "current_value": 12,
                            "source": "Promotion test",
                            "notes": "Monitoring promotion test.",
                        },
                    )
                    self.assertEqual(monitoring_response.status_code, 201)
                    self.assertEqual(monitoring_response.headers["X-Funnel-Served-By"], "postgres")
                    self.assertEqual(monitoring_response.headers["X-Funnel-Legacy-Fallback"], "0")
        finally:
            tempdir.cleanup()

    def test_promoted_report_preview_serves_from_postgres(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    report_id = int(conn.execute("SELECT id FROM reports ORDER BY id LIMIT 1").fetchone()["id"])
                finally:
                    conn.close()
                with TestClient(create_app()) as client:
                    response = client.post(f"/api/reports/{report_id}/preview", json={"finalize": False})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Funnel-Execution-Policy"], "postgres_primary_with_legacy_fallback")
                self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")
        finally:
            tempdir.cleanup()

    def test_promoted_document_upload_serves_from_postgres(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    company_id = int(conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()["id"])
                finally:
                    conn.close()
                with TestClient(create_app()) as client:
                    response = client.post(
                        "/api/documents",
                        files={"file": ("promotion.txt", b"promotion document", "text/plain")},
                        data={"company_id": str(company_id), "notes": "Promotion upload"},
                    )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")
                self.assertTrue(response.json()["documents"])
        finally:
            tempdir.cleanup()

    def test_promoted_document_download_serves_from_postgres(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    row = conn.execute(
                        "SELECT id FROM documents WHERE storage_path != '' ORDER BY id LIMIT 1"
                    ).fetchone()
                    if row is None:
                        self.skipTest("No documents available for download promotion test.")
                    document_id = int(row["id"])
                finally:
                    conn.close()
                with TestClient(create_app()) as client:
                    response = client.get(f"/api/documents/{document_id}/download")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")
        finally:
            tempdir.cleanup()

    def test_remote_authoritative_document_download_records_storage_fallback(self) -> None:
        tempdir, env, _ = self.make_runtime()
        env["FUNNEL_V2_STORAGE_MODE"] = "s3_compatible"
        env["FUNNEL_V2_STORAGE_BUCKET"] = "hosted-bucket"
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    row = conn.execute(
                        "SELECT id FROM documents WHERE storage_path != '' ORDER BY id LIMIT 1"
                    ).fetchone()
                    if row is None:
                        self.skipTest("No documents available for download promotion test.")
                    document_id = int(row["id"])
                finally:
                    conn.close()
                with TestClient(create_app()) as client:
                    storage = client.app.state.storage
                    storage.settings.storage_mode = "s3_compatible"
                    storage.object_exists = lambda key, local_path=None: True  # type: ignore[method-assign]
                    storage.response_for_file = lambda **kwargs: (  # type: ignore[method-assign]
                        Response(content=b"fallback-bytes", media_type=kwargs["media_type"], headers=kwargs["headers"]),
                        StorageResolution(
                            used_remote=False,
                            used_local_fallback=True,
                            remote_authoritative=True,
                            detail="remote object missing in test",
                        ),
                    )
                    response = client.get(f"/api/documents/{document_id}/download")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Funnel-Storage-Fallback"], "1")
                artifact = Path(response.headers["X-Funnel-Storage-Artifact"])
                self.assertTrue(artifact.exists())
        finally:
            tempdir.cleanup()

    def test_promoted_document_normalized_serves_from_postgres_when_ready(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(Path(env["FUNNEL_V2_SQLITE_PATH"]))
                try:
                    row = conn.execute(
                        """
                        SELECT id
                        FROM documents
                        WHERE normalized_status NOT IN ('', 'pending')
                          AND normalized_text_path != ''
                        ORDER BY id
                        LIMIT 1
                        """
                    ).fetchone()
                    if row is None:
                        self.skipTest("No normalized documents available for normalized promotion test.")
                    document_id = int(row["id"])
                finally:
                    conn.close()
                with TestClient(create_app()) as client:
                    response = client.get(f"/api/documents/{document_id}/normalized")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Funnel-Served-By"], "postgres")
                self.assertEqual(response.headers["X-Funnel-Legacy-Fallback"], "0")
        finally:
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
