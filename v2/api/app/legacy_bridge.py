from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

V1_ROOT = Path(__file__).resolve().parents[4]
if str(V1_ROOT) not in sys.path:
    sys.path.insert(0, str(V1_ROOT))

from funnel_app import db as legacy_db

from app.config import Settings
from app.runtime_state import read_cutover_state
from app.runtime_state import read_write_freeze_state


@dataclass(slots=True)
class LegacyBridge:
    settings: Settings
    instance_id: str
    started_at: str

    @contextmanager
    def open_db(self):
        conn = legacy_db.connect(self.settings.sqlite_path)
        try:
            yield conn
        finally:
            conn.close()

    def ensure_database(self) -> None:
        legacy_db.setup_database(self.settings.sqlite_path, auto_confirm_seed=True)

    def request_id(self) -> str:
        return uuid.uuid4().hex

    def health_payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ok",
        }

    def runtime_health_payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        write_freeze = read_write_freeze_state(self.settings)
        cutover_state = read_cutover_state(self.settings)
        return {
            "ok": True,
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "pid": os.getpid(),
            "db_path": str(self.settings.sqlite_path),
            "upload_dir": str(self.settings.upload_root),
            "schema_version": legacy_db.database_schema_version(conn),
            "worker": legacy_db.background_job_health(conn),
            "storage_mode": self.settings.storage_mode,
            "write_freeze": write_freeze,
            "cutover_state": cutover_state,
        }

    def bootstrap_payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        return {
            "dashboard": legacy_db.dashboard(conn),
            "settings_summary": legacy_db.settings_summary(conn),
            "stages": legacy_db.list_stages(conn),
            "buckets": legacy_db.BUCKETS,
            "report_actions": legacy_db.REPORT_ACTIONS,
        }

    def serialize(self, payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def build_bridge(settings: Settings) -> LegacyBridge:
    instance_id = settings.instance_id or uuid.uuid4().hex[:12]
    bridge = LegacyBridge(settings=settings, instance_id=instance_id, started_at=legacy_db.now_iso())
    bridge.ensure_database()
    return bridge
