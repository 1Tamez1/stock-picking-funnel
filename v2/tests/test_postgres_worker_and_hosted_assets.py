from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.postgres_services import PostgresCompatibilityStore
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


class PostgresWorkerAndHostedAssetsTest(unittest.TestCase):
    def make_runtime(self) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str], Path]:
        tempdir = tempfile.TemporaryDirectory(dir=ROOT / "contracts")
        runtime_root = Path(tempdir.name)
        sqlite_path = runtime_root / "funnel.db"
        upload_root = runtime_root / "uploads"
        shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_path)
        shutil.copytree(V1_ROOT / "var" / "uploads", upload_root)
        env = {
            "FUNNEL_V2_BACKEND_MODE": "postgres_verify",
            "FUNNEL_V2_CONTRACT_DIR": str(runtime_root / "contracts"),
            "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(runtime_root / 'shadow.db').as_posix()}",
            "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
            "FUNNEL_V2_UPLOAD_DIR": str(upload_root),
        }
        return tempdir, env, sqlite_path

    def test_postgres_worker_processes_pending_document_job(self) -> None:
        tempdir, env, sqlite_path = self.make_runtime()
        try:
            with temporary_env(env):
                conn = legacy_db.connect(sqlite_path)
                try:
                    conn.execute("DELETE FROM background_jobs")
                    conn.commit()
                    company_id = int(conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()["id"])
                    document = legacy_db.save_document(
                        conn,
                        Path(env["FUNNEL_V2_UPLOAD_DIR"]),
                        company_id,
                        "postgres-worker.txt",
                        b"postgres worker text",
                        notes="worker test",
                        mime_type="text/plain",
                    )
                    document_id = int(document["id"])
                finally:
                    conn.close()

                settings = load_settings()
                shadow = ShadowBackend(settings)
                try:
                    shadow.sync_from_source("worker-test-seed", force=True)
                    store = PostgresCompatibilityStore(shadow)
                    processed = store.process_next_background_job("postgres-test-worker")
                    self.assertTrue(processed)
                    payload = store.document_status(document_id)
                    self.assertIn(payload["document"]["normalized_status"], {"ready", "limited", "failed"})
                finally:
                    shadow.close()
        finally:
            tempdir.cleanup()

    def test_hosted_stack_assets_exist(self) -> None:
        deploy_root = ROOT / "deploy"
        for path in (
            deploy_root / "Dockerfile.api",
            deploy_root / "Dockerfile.worker",
            deploy_root / "Dockerfile.web",
            deploy_root / "api-entrypoint.sh",
            deploy_root / "worker-entrypoint.sh",
            deploy_root / ".env.staging.example",
            ROOT / "scripts" / "manage_owner_tokens.py",
            ROOT / "scripts" / "migrate_uploads_to_storage.py",
            ROOT / "scripts" / "run_hosted_smoke.py",
            ROOT / "scripts" / "audit_integrity.py",
            ROOT / "scripts" / "repair_integrity.py",
            ROOT / "scripts" / "set_cutover_state.py",
            ROOT / "scripts" / "rehearse_cutover.sh",
            ROOT / "scripts" / "cutback_hosted_state.sh",
        ):
            self.assertTrue(path.exists(), f"Missing hosted asset: {path}")

        compose = (deploy_root / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("Dockerfile.api", compose)
        self.assertIn("Dockerfile.worker", compose)
        self.assertIn("Dockerfile.web", compose)


if __name__ == "__main__":
    unittest.main()
