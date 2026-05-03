from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
V1_ROOT = ROOT.parent

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
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


def main() -> None:
    shadow_root = ROOT / "contracts" / "shadow"
    shadow_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "contracts") as runtime_dir:
        runtime_root = Path(runtime_dir)
        sqlite_copy = runtime_root / "funnel.db"
        shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_copy)
        base_env = {
            "FUNNEL_V2_CONTRACT_DIR": str(ROOT / "contracts"),
            "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(shadow_root / 'verify-shadow.db').as_posix()}",
            "FUNNEL_V2_SQLITE_PATH": str(sqlite_copy),
            "FUNNEL_V2_UPLOAD_DIR": str(V1_ROOT / "var" / "uploads"),
        }
        conn = legacy_db.connect(sqlite_copy)
        try:
            first_company = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
            first_report = conn.execute("SELECT id FROM reports ORDER BY id LIMIT 1").fetchone()
            first_template = conn.execute("SELECT id FROM templates ORDER BY id LIMIT 1").fetchone()
        finally:
            conn.close()

        def exercise_common_routes(client: TestClient) -> None:
            client.get("/api/bootstrap")
            client.get("/api/stages")
            client.get("/api/companies")
            client.get("/api/reports")
            client.get("/api/templates")
            client.get("/api/monitoring")
            if first_template is not None:
                client.get(f"/api/templates/{int(first_template['id'])}")
            if first_company is not None:
                client.get(f"/api/companies/{int(first_company['id'])}")
            if first_report is not None:
                report_id = int(first_report["id"])
                client.get(f"/api/reports/{report_id}")
                client.post(f"/api/reports/{report_id}/preview", json={"finalize": False})

        with temporary_env({**base_env, "FUNNEL_V2_BACKEND_MODE": "shadow"}):
            with TestClient(create_app()) as client:
                exercise_common_routes(client)
                client.post("/api/companies", json={"ticker": "SHDWART", "name": "Shadow Artifact Company"})
                shadow = ShadowBackend(load_settings())
                try:
                    shadow.observe_worker_cycle("artifact-smoke")
                finally:
                    shadow.close()

        with temporary_env({**base_env, "FUNNEL_V2_BACKEND_MODE": "postgres_verify"}):
            with TestClient(create_app()) as client:
                exercise_common_routes(client)


if __name__ == "__main__":
    main()
