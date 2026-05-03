from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
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
from app.runtime_state import read_cutover_state
from app.runtime_state import set_cutover_state
from app.runtime_state import read_write_freeze_state
from app.runtime_state import set_write_freeze
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


class HostedRuntimeControlsTest(unittest.TestCase):
    def make_runtime(self) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str]]:
        tempdir = tempfile.TemporaryDirectory(dir=ROOT / "contracts")
        runtime_root = Path(tempdir.name)
        sqlite_path = runtime_root / "funnel.db"
        upload_root = runtime_root / "uploads"
        shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_path)
        shutil.copytree(V1_ROOT / "var" / "uploads", upload_root)
        env = {
            "FUNNEL_V2_BACKEND_MODE": "legacy",
            "FUNNEL_V2_CONTRACT_DIR": str(runtime_root / "contracts"),
            "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(runtime_root / 'shadow.db').as_posix()}",
            "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
            "FUNNEL_V2_UPLOAD_DIR": str(upload_root),
        }
        return tempdir, env

    def test_write_freeze_blocks_mutations_and_surfaces_in_runtime_health(self) -> None:
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

                freeze = set_write_freeze(
                    settings,
                    enabled=True,
                    reason="cutover_rehearsal",
                    message="Writes are frozen during hosted validation.",
                    source="unit-test",
                    created_at="2026-04-21T12:00:00+00:00",
                )
                self.assertTrue(freeze["write_frozen"])
                self.assertEqual(read_write_freeze_state(settings)["reason"], "cutover_rehearsal")
                cutover = set_cutover_state(
                    settings,
                    phase="rehearsal",
                    status="running",
                    rollback_authority="sqlite",
                    cutback_required=False,
                    reason="cutover_rehearsal",
                    message="Hosted cutover rehearsal is running.",
                    source="unit-test",
                    created_at="2026-04-21T12:05:00+00:00",
                    manifest_path="/tmp/rehearsal-manifest.json",
                )
                self.assertEqual(cutover["phase"], "rehearsal")
                self.assertEqual(read_cutover_state(settings)["status"], "running")

                with TestClient(create_app()) as client:
                    login = client.post("/api/session/login", json={"email": "owner@example.com", "password": "secret-pass"})
                    self.assertEqual(login.status_code, 201)

                    bootstrap = client.get("/api/bootstrap")
                    self.assertEqual(bootstrap.status_code, 200)

                    blocked = client.post("/api/companies", json={"ticker": "FROZEN", "name": "Should Not Create"})
                    self.assertEqual(blocked.status_code, 503)
                    self.assertEqual(blocked.json()["code"], "write_frozen")

                    runtime = client.get("/api/health/runtime")
                    self.assertEqual(runtime.status_code, 200)
                    self.assertTrue(runtime.json()["write_freeze"]["write_frozen"])
                    self.assertEqual(runtime.json()["cutover_state"]["phase"], "rehearsal")
                    self.assertEqual(runtime.json()["cutover_state"]["status"], "running")
        finally:
            tempdir.cleanup()

    def test_hosted_runtime_assets_and_scripts_exist(self) -> None:
        expected = [
            ROOT / "deploy" / "up.sh",
            ROOT / "deploy" / "down.sh",
            ROOT / "deploy" / "reset.sh",
            ROOT / "deploy" / "validate.sh",
            ROOT / "deploy" / ".env.validation.example",
            ROOT / "scripts" / "run_hosted_validation.py",
            ROOT / "scripts" / "verify_owner_token.py",
            ROOT / "scripts" / "set_write_freeze.py",
            ROOT / "scripts" / "set_cutover_state.py",
        ]
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing hosted runtime asset: {path}")

        compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("../contracts:/app/v2/contracts", compose)
        up_script = (ROOT / "deploy" / "up.sh").read_text(encoding="utf-8")
        self.assertIn("up-failure-report.json", up_script)
        self.assertIn("wait_for_service", up_script)

    def test_new_hosted_scripts_expose_help(self) -> None:
        for script in (
            ROOT / "scripts" / "run_hosted_validation.py",
            ROOT / "scripts" / "verify_owner_token.py",
            ROOT / "scripts" / "set_write_freeze.py",
            ROOT / "scripts" / "set_cutover_state.py",
            ROOT / "deploy" / "validate.sh",
        ):
            with self.subTest(script=script):
                if script.suffix == ".sh":
                    command = ["bash", str(script), "--help"]
                else:
                    command = [sys.executable, str(script), "--help"]
                result = subprocess.run(command, cwd=ROOT.parent, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
