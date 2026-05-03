from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from . import db
from .config import app_root, db_path, max_upload_bytes, upload_dir


class AppContext:
    def __init__(
        self,
        database: Path | None = None,
        uploads: Path | None = None,
        max_request_bytes: int | None = None,
    ) -> None:
        self.database = database or db_path()
        self.uploads = uploads or upload_dir()
        self.max_upload_bytes = max_request_bytes if max_request_bytes is not None else max_upload_bytes()
        self.static_root = app_root() / "static"


class AppRuntime:
    def __init__(self, context: AppContext | None = None) -> None:
        self.context = context or AppContext()
        self.instance_id = uuid.uuid4().hex[:12]
        self.started_at = db.now_iso()
        self.worker_id = f"normalize-{os.getpid()}-{self.instance_id}"
        self.last_job_at = ""
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._initialized = False

    def initialize(self, *, auto_confirm_seed: bool = False) -> None:
        if self._initialized:
            return
        db.setup_database(self.context.database, auto_confirm_seed=auto_confirm_seed)
        self._initialized = True
        self.start_worker()

    def start_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"funnel-worker-{self.instance_id}",
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            try:
                did_work = db.process_next_background_job(
                    self.context.database,
                    self.context.uploads,
                    self.worker_id,
                )
            except Exception:
                did_work = False
            if did_work:
                self.last_job_at = db.now_iso()
                continue
            self._worker_stop.wait(0.75)

    def stop(self) -> None:
        self._worker_stop.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2)

    def worker_health(self, conn) -> dict[str, object]:
        return {
            "alive": bool(self._worker_thread and self._worker_thread.is_alive()),
            "worker_id": self.worker_id,
            "last_job_at": self.last_job_at,
            **db.background_job_health(conn),
        }
