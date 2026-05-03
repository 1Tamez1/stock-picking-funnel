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


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.db.models import Company
from app.main import create_app
from app.shadow import ShadowBackend
from funnel_app import db as legacy_db


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


class ShadowBackendTest(unittest.TestCase):
    def make_runtime(self, *, copy_sqlite: bool = False) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str], Path]:
        tempdir = tempfile.TemporaryDirectory(dir=ROOT / "contracts")
        runtime_root = Path(tempdir.name)
        sqlite_path = runtime_root / "funnel.db"
        if copy_sqlite:
            shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_path)
        else:
            sqlite_path = V1_ROOT / "var" / "funnel.db"
        env = {
            "FUNNEL_V2_BACKEND_MODE": "shadow",
            "FUNNEL_V2_CONTRACT_DIR": str(runtime_root / "contracts"),
            "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(runtime_root / 'shadow.db').as_posix()}",
            "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
            "FUNNEL_V2_UPLOAD_DIR": str(V1_ROOT / "var" / "uploads"),
        }
        return tempdir, env, sqlite_path

    def test_shadow_sync_builds_clean_import_manifest(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                settings = load_settings()
                shadow = ShadowBackend(settings)
                try:
                    result = shadow.sync_from_source("unit-test-import", force=True)
                    self.assertIsNotNone(result)
                    self.assertEqual(result.status, "ok")
                    self.assertTrue(result.manifest_path.exists())
                    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(payload["status"], "ok")
                    self.assertEqual(payload["tables"]["companies"]["source_count"], payload["tables"]["companies"]["shadow_count"])
                    self.assertEqual(payload["tables"]["reports"]["source_digest"], payload["tables"]["reports"]["shadow_digest"])
                finally:
                    shadow.close()
        finally:
            tempdir.cleanup()

    def test_shadow_read_keeps_bootstrap_payload_and_writes_read_artifact(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                with TestClient(create_app()) as client:
                    conn = legacy_db.connect(V1_ROOT / "var" / "funnel.db")
                    try:
                        response = client.get("/api/bootstrap")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(
                            response.json(),
                            {
                                "dashboard": legacy_db.dashboard(conn),
                                "settings_summary": legacy_db.settings_summary(conn),
                                "stages": legacy_db.list_stages(conn),
                                "buckets": legacy_db.BUCKETS,
                                "report_actions": legacy_db.REPORT_ACTIONS,
                            },
                        )
                    finally:
                        conn.close()
                read_dir = Path(env["FUNNEL_V2_CONTRACT_DIR"]) / "shadow" / "read-parity"
                artifacts = sorted(read_dir.glob("*.json"))
                self.assertTrue(artifacts, "Expected read parity artifacts to be written in shadow mode.")
                latest = json.loads(artifacts[-1].read_text(encoding="utf-8"))
                self.assertEqual(latest["status"], "ok")
        finally:
            tempdir.cleanup()

    def test_shadow_write_keeps_legacy_response_and_writes_write_artifact(self) -> None:
        tempdir, env, sqlite_path = self.make_runtime(copy_sqlite=True)
        try:
            with temporary_env(env):
                with TestClient(create_app()) as client:
                    response = client.post(
                        "/api/companies",
                        json={"ticker": "SHDWTEST", "name": "Shadow Test Company"},
                    )
                    self.assertEqual(response.status_code, 201)
                    payload = response.json()["company"]
                    self.assertEqual(payload["ticker"], "SHDWTEST")

                conn = legacy_db.connect(sqlite_path)
                try:
                    row = conn.execute("SELECT ticker, name FROM companies WHERE ticker = 'SHDWTEST'").fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row["name"], "Shadow Test Company")
                finally:
                    conn.close()

                write_dir = Path(env["FUNNEL_V2_CONTRACT_DIR"]) / "shadow" / "write-parity"
                artifacts = sorted(write_dir.glob("*.json"))
                self.assertTrue(artifacts, "Expected write parity artifacts to be written in shadow mode.")
                latest = json.loads(artifacts[-1].read_text(encoding="utf-8"))
                self.assertEqual(latest["status"], "ok")
                manifest = json.loads((Path(env["FUNNEL_V2_CONTRACT_DIR"]) / "shadow" / "migration-import-manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "ok")
        finally:
            tempdir.cleanup()

    def test_worker_observer_writes_worker_artifact(self) -> None:
        tempdir, env, _ = self.make_runtime()
        try:
            with temporary_env(env):
                settings = load_settings()
                shadow = ShadowBackend(settings)
                try:
                    artifact = shadow.observe_worker_cycle("unit-test-worker")
                    self.assertIsNotNone(artifact)
                    self.assertEqual(artifact["status"], "ok")
                    worker_dir = Path(env["FUNNEL_V2_CONTRACT_DIR"]) / "shadow" / "worker-parity"
                    self.assertTrue(any(worker_dir.glob("*.json")))
                finally:
                    shadow.close()
        finally:
            tempdir.cleanup()

    def test_shadow_sync_reuses_existing_manifest_across_processes(self) -> None:
        tempdir, env, _ = self.make_runtime(copy_sqlite=True)
        try:
            with temporary_env(env):
                settings = load_settings()
                first = ShadowBackend(settings)
                try:
                    first.sync_from_source("initial-sync", force=True)
                    session = first.session_factory()()
                    try:
                        company = session.get(Company, 1)
                        self.assertIsNotNone(company)
                        company.name = "Shadow Edited Name"
                        session.commit()
                    finally:
                        session.close()
                finally:
                    first.close()

                second = ShadowBackend(settings)
                try:
                    second.sync_from_source("second-process", force=False)
                    session = second.session_factory()()
                    try:
                        company = session.get(Company, 1)
                        self.assertIsNotNone(company)
                        self.assertEqual(company.name, "Shadow Edited Name")
                    finally:
                        session.close()
                finally:
                    second.close()
        finally:
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
