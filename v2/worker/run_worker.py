from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from funnel_app import db as legacy_db

from app.config import load_settings
from app.db.models import Document
from app.postgres_services import PostgresCompatibilityStore
from app.shadow import ShadowBackend
from app.storage import StorageAdapter


def mirror_all_documents(settings, storage: StorageAdapter) -> None:
    conn = legacy_db.connect(settings.sqlite_path)
    try:
        rows = conn.execute("SELECT id FROM documents ORDER BY id").fetchall()
        for row in rows:
            document = legacy_db.get_document(conn, int(row["id"]))
            if document:
                storage.mirror_document_record(document)
    finally:
        conn.close()


def mirror_shadow_documents(shadow_backend: ShadowBackend, storage: StorageAdapter) -> None:
    session = shadow_backend.session_factory()()
    try:
        rows = session.execute(Document.__table__.select().order_by(Document.id)).mappings().all()
        for row in rows:
            document = {
                "id": int(row["id"]),
                "storage_key": row["storage_key"],
                "storage_path": row["legacy_storage_path"],
                "stored_name": row["stored_name"],
                "mime_type": row["mime_type"],
                "normalized_storage_key": row["normalized_storage_key"],
                "normalized_text_path": row["normalized_text_path"],
            }
            storage.mirror_document_record(document)
    finally:
        session.close()


def main() -> None:
    settings = load_settings()
    worker_id = os.environ.get("FUNNEL_V2_WORKER_ID", "v2-compat-worker")
    shadow_backend = ShadowBackend(settings)
    postgres_store = PostgresCompatibilityStore(shadow_backend)
    storage = StorageAdapter(settings)
    while True:
        did_work = False
        if settings.backend_mode == "postgres_verify":
            try:
                did_work = postgres_store.process_next_background_job(worker_id)
                if did_work:
                    mirror_shadow_documents(shadow_backend, storage)
                    shadow_backend.observe_worker_cycle(worker_id)
                    reconciliation_path, reconciliation = shadow_backend.record_state_reconciliation(
                        category="worker.lifecycle",
                        request_key=worker_id,
                    )
                    if reconciliation.get("status") != "ok":
                        shadow_backend.record_fallback_event(
                            category="worker.lifecycle",
                            request_key=worker_id,
                            policy="postgres_primary_with_legacy_fallback",
                            reason="state_reconciliation_mismatch",
                            primary_backend="postgres",
                            detail=f"{len(reconciliation.get('diffs') or [])} worker-state mismatches",
                            artifact_path=reconciliation_path,
                        )
            except Exception as exc:
                shadow_backend.record_fallback_event(
                    category="worker.lifecycle",
                    request_key=worker_id,
                    policy="postgres_primary_with_legacy_fallback",
                    reason="postgres_unavailable",
                    primary_backend="postgres",
                    detail=str(exc),
                )
                did_work = legacy_db.process_next_background_job(settings.sqlite_path, settings.upload_root, worker_id)
                if did_work:
                    mirror_all_documents(settings, storage)
                    shadow_backend.sync_from_source(reason=f"worker-fallback:{worker_id}", force=True)
                    shadow_backend.observe_worker_cycle(worker_id)
        else:
            did_work = legacy_db.process_next_background_job(settings.sqlite_path, settings.upload_root, worker_id)
        if did_work:
            if settings.backend_mode != "postgres_verify":
                mirror_all_documents(settings, storage)
                shadow_backend.sync_from_source(reason=f"worker-cycle:{worker_id}", force=True)
                shadow_backend.observe_worker_cycle(worker_id)
                reconciliation_path, reconciliation = shadow_backend.record_state_reconciliation(
                    category="worker.lifecycle",
                    request_key=worker_id,
                )
                if reconciliation.get("status") != "ok":
                    shadow_backend.record_fallback_event(
                        category="worker.lifecycle",
                        request_key=worker_id,
                        policy="shadow_compare",
                        reason="state_reconciliation_mismatch",
                        primary_backend="legacy",
                        detail=f"{len(reconciliation.get('diffs') or [])} worker-state mismatches",
                        artifact_path=reconciliation_path,
                    )
            continue
        time.sleep(0.75)


if __name__ == "__main__":
    main()
