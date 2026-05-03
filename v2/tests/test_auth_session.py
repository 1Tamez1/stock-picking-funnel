from __future__ import annotations

import contextlib
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

from app.auth import AuthService
from app.config import load_settings
from app.main import create_app
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


class AuthSessionTest(unittest.TestCase):
    def make_runtime(self) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str]]:
        tempdir = tempfile.TemporaryDirectory(dir=ROOT / "contracts")
        runtime_root = Path(tempdir.name)
        sqlite_path = runtime_root / "funnel.db"
        shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_path)
        env = {
            "FUNNEL_V2_BACKEND_MODE": "legacy",
            "FUNNEL_V2_CONTRACT_DIR": str(runtime_root / "contracts"),
            "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(runtime_root / 'shadow.db').as_posix()}",
            "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
            "FUNNEL_V2_UPLOAD_DIR": str(V1_ROOT / "var" / "uploads"),
        }
        return tempdir, env

    def test_owner_bootstrap_login_logout_and_protected_runtime(self) -> None:
        tempdir, env = self.make_runtime()
        try:
            with temporary_env(env):
                settings = load_settings()
                shadow = ShadowBackend(settings)
                try:
                    auth = AuthService(shadow)
                    auth.bootstrap_owner(email="owner@example.com", password="secret-pass", display_name="Owner")
                finally:
                    shadow.close()

                with TestClient(create_app()) as client:
                    session = client.get("/api/session")
                    self.assertEqual(session.status_code, 200)
                    self.assertTrue(session.json()["required"])
                    self.assertFalse(session.json()["authenticated"])

                    protected = client.get("/api/bootstrap")
                    self.assertEqual(protected.status_code, 401)

                    runtime = client.get("/api/health/runtime")
                    self.assertEqual(runtime.status_code, 401)

                    login = client.post(
                        "/api/session/login",
                        json={"email": "owner@example.com", "password": "secret-pass"},
                    )
                    self.assertEqual(login.status_code, 201)
                    self.assertTrue(login.json()["authenticated"])

                    bootstrap = client.get("/api/bootstrap")
                    self.assertEqual(bootstrap.status_code, 200)

                    runtime = client.get("/api/health/runtime")
                    self.assertEqual(runtime.status_code, 200)
                    self.assertIn("db_path", runtime.json())

                    logout = client.post("/api/session/logout")
                    self.assertEqual(logout.status_code, 200)

                    protected_again = client.get("/api/bootstrap")
                    self.assertEqual(protected_again.status_code, 401)
        finally:
            tempdir.cleanup()

    def test_owner_bearer_token_authenticates_protected_routes(self) -> None:
        tempdir, env = self.make_runtime()
        try:
            with temporary_env(env):
                settings = load_settings()
                shadow = ShadowBackend(settings)
                try:
                    auth = AuthService(shadow)
                    auth.bootstrap_owner(email="owner@example.com", password="secret-pass", display_name="Owner")
                    token_payload = auth.issue_api_token(label="Runbook Token", expires_in_days=30)
                finally:
                    shadow.close()

                headers = {"Authorization": f"Bearer {token_payload['token']}"}
                with TestClient(create_app()) as client:
                    session = client.get("/api/session", headers=headers)
                    self.assertEqual(session.status_code, 200)
                    self.assertTrue(session.json()["authenticated"])

                    bootstrap = client.get("/api/bootstrap", headers=headers)
                    self.assertEqual(bootstrap.status_code, 200)

                    runtime = client.get("/api/health/runtime", headers=headers)
                    self.assertEqual(runtime.status_code, 200)
        finally:
            tempdir.cleanup()

    def test_mcp_bearer_token_scopes_block_unscoped_writes(self) -> None:
        tempdir, env = self.make_runtime()
        try:
            with temporary_env(env):
                settings = load_settings()
                shadow = ShadowBackend(settings)
                try:
                    auth = AuthService(shadow)
                    auth.bootstrap_owner(email="owner@example.com", password="secret-pass", display_name="Owner")
                    token_payload = auth.issue_api_token(label="Read Token", expires_in_days=30, scopes=["read"])
                finally:
                    shadow.close()

                headers = {"Authorization": f"Bearer {token_payload['token']}"}
                with TestClient(create_app()) as client:
                    reports = client.get("/api/reports?include_drafts=1&per_page=1", headers=headers)
                    self.assertEqual(reports.status_code, 200)
                    report_id = int(reports.json()["reports"][0]["id"])
                    sections = client.get(f"/api/reports/{report_id}/sections", headers=headers)
                    self.assertEqual(sections.status_code, 200)
                    section_id = sections.json()["sections"][0]["section_id"]

                    read_call = client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {
                                "name": "read_report_section",
                                "arguments": {"report_id": report_id, "section_id": section_id},
                            },
                        },
                    )
                    self.assertEqual(read_call.status_code, 200)
                    self.assertIn("result", read_call.json())

                    write_call = client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "patch_report_section",
                                "arguments": {
                                    "report_id": report_id,
                                    "section_id": section_id,
                                    "expected_report_revision": 1,
                                    "expected_section_revision": 1,
                                },
                            },
                        },
                    )
                    self.assertEqual(write_call.status_code, 200)
                    self.assertEqual(write_call.json()["error"]["code"], -32003)
                    self.assertIn("write_reports", write_call.json()["error"]["message"])
        finally:
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
