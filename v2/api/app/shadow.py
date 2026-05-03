from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import BackgroundJob
from app.db.models import Company
from app.db.models import Document
from app.db.models import EndpointSnapshot
from app.db.models import MonitoringRule
from app.db.models import OwnerUser
from app.db.models import Report
from app.db.models import ReportSource
from app.db.models import Stage
from app.db.models import Template
from app.db.models import UserSession
from app.db.models import Workspace
from app.db.session import build_engine
from app.db.session import build_session_factory

V1_ROOT = Path(__file__).resolve().parents[4]
if str(V1_ROOT) not in sys.path:
    sys.path.insert(0, str(V1_ROOT))

from funnel_app import db as legacy_db

SHADOW_WORKSPACE_ID = 1
SHADOW_WORKSPACE_PUBLIC_ID = "shadow-default-workspace"
SHADOW_WORKSPACE_NAME = "Default Workspace"
SHADOW_WORKSPACE_SLUG = "default-workspace"

TABLE_ORDER = [
    "stages",
    "companies",
    "templates",
    "reports",
    "documents",
    "report_sources",
    "background_jobs",
    "monitoring_rules",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str, fallback: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:120] or fallback


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return now_utc()
    return datetime.fromisoformat(value)


def canonical_timestamp(value: str | datetime | None) -> str:
    if value in (None, ""):
        return ""
    parsed = value if isinstance(value, datetime) else parse_timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


def json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_payload(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_payload(item) for item in value]
    return value


def strip_transport_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_transport_fields(item)
            for key, item in value.items()
            if key not in {"request_id"}
        }
    if isinstance(value, list):
        return [strip_transport_fields(item) for item in value]
    return value


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def diff_values(source: Any, shadow: Any, path: str = "") -> list[dict[str, Any]]:
    if source == shadow:
        return []
    if isinstance(source, dict) and isinstance(shadow, dict):
        diffs: list[dict[str, Any]] = []
        keys = sorted(set(source) | set(shadow))
        for key in keys:
            next_path = f"{path}.{key}" if path else key
            if key not in source:
                diffs.append({"path": next_path, "source": None, "shadow": shadow[key]})
                continue
            if key not in shadow:
                diffs.append({"path": next_path, "source": source[key], "shadow": None})
                continue
            diffs.extend(diff_values(source[key], shadow[key], next_path))
        return diffs
    if isinstance(source, list) and isinstance(shadow, list):
        diffs = []
        count = max(len(source), len(shadow))
        for index in range(count):
            next_path = f"{path}[{index}]"
            if index >= len(source):
                diffs.append({"path": next_path, "source": None, "shadow": shadow[index]})
                continue
            if index >= len(shadow):
                diffs.append({"path": next_path, "source": source[index], "shadow": None})
                continue
            diffs.extend(diff_values(source[index], shadow[index], next_path))
        return diffs
    return [{"path": path or "$", "source": source, "shadow": shadow}]


def table_digest(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json_dump(rows).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_storage_key(upload_root: Path, file_path: str | None, fallback: str) -> str:
    if not file_path:
        return fallback
    candidate = Path(file_path)
    try:
        return str(candidate.resolve().relative_to(upload_root.resolve()))
    except ValueError:
        return fallback


def upload_tree_manifest(upload_root: Path) -> list[dict[str, Any]]:
    if not upload_root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(node for node in upload_root.rglob("*") if node.is_file()):
        items.append(
            {
                "path": str(path.relative_to(upload_root)),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return items


def sqlite_query_rows(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    return list(conn.execute(query).fetchall())


def canonical_sqlite_rows(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        "stages": [
            {
                "id": int(row["id"]),
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "sequence": int(row["sequence"]),
                "is_active": bool(row["is_active"]),
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM stages ORDER BY id")
        ],
        "companies": [
            {
                "id": int(row["id"]),
                "ticker": row["ticker"],
                "name": row["name"],
                "bucket": row["bucket"],
                "current_stage_id": int(row["current_stage_id"]) if row["current_stage_id"] is not None else None,
                "notes": row["notes"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM companies ORDER BY id")
        ],
        "templates": [
            {
                "id": int(row["id"]),
                "stage_id": int(row["stage_id"]),
                "name": row["name"],
                "version": int(row["version"]),
                "description": row["description"],
                "markdown": row["markdown"],
                "schema_json": normalize_payload(json_loads(row["schema_json"], {})),
                "is_active": bool(row["is_active"]),
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM templates ORDER BY id")
        ],
        "reports": [
            {
                "id": int(row["id"]),
                "company_id": int(row["company_id"]),
                "stage_id": int(row["stage_id"]),
                "template_id": int(row["template_id"]),
                "title": row["title"],
                "report_month": row["report_month"],
                "revision": int(row["revision"]),
                "responses_json": normalize_payload(json_loads(row["responses_json"], {})),
                "metrics_json": normalize_payload(json_loads(row["metrics_json"], {})),
                "section_ratings_json": normalize_payload(json_loads(row["section_ratings_json"], {})),
                "data_quality_json": normalize_payload(json_loads(row["data_quality_json"], {})),
                "field_sources_json": normalize_payload(json_loads(row["field_sources_json"], {})),
                "field_notes_json": normalize_payload(json_loads(row["field_notes_json"], {})),
                "field_exceptions_json": normalize_payload(json_loads(row["field_exceptions_json"], {})),
                "result": row["result"],
                "summary": row["summary"],
                "watchlist_conditions": row["watchlist_conditions"],
                "watchlist_objective_rules_json": normalize_payload(json_loads(row["watchlist_objective_rules_json"], [])),
                "watchlist_subjective_rules": row["watchlist_subjective_rules"],
                "archive_red_flags": row["archive_red_flags"],
                "next_action": row["next_action"],
                "review_date": row["review_date"],
                "completed_at": row["completed_at"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM reports ORDER BY id")
        ],
        "documents": [
            {
                "id": int(row["id"]),
                "company_id": int(row["company_id"]),
                "report_id": int(row["report_id"]) if row["report_id"] is not None else None,
                "original_name": row["original_name"],
                "stored_name": row["stored_name"],
                "storage_path": row["storage_path"],
                "mime_type": row["mime_type"],
                "size_bytes": int(row["size_bytes"]),
                "notes": row["notes"],
                "normalized_text_path": row["normalized_text_path"],
                "normalized_status": row["normalized_status"],
                "normalized_format": row["normalized_format"],
                "normalized_method": row["normalized_method"],
                "normalized_notes": row["normalized_notes"],
                "normalized_preview": row["normalized_preview"],
                "normalized_updated_at": row["normalized_updated_at"],
                "uploaded_at": row["uploaded_at"],
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM documents ORDER BY id")
        ],
        "report_sources": [
            {
                "id": int(row["id"]),
                "report_id": int(row["report_id"]),
                "document_id": int(row["document_id"]) if row["document_id"] is not None else None,
                "title": row["title"],
                "capture_kind": row["capture_kind"],
                "source_type": row["source_type"],
                "evidence_grade": row["evidence_grade"],
                "confidence": row["confidence"],
                "tags_json": normalize_payload(json_loads(row["tags_json"], [])),
                "url": row["url"],
                "canonical_url": row["canonical_url"],
                "link_only_reason": row["link_only_reason"],
                "snapshot_guidance_acknowledged": bool(row["snapshot_guidance_acknowledged"]),
                "capture_state": row["capture_state"],
                "capture_error": row["capture_error"],
                "citation": row["citation"],
                "notes": row["notes"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM report_sources ORDER BY id")
        ],
        "background_jobs": [
            {
                "id": int(row["id"]),
                "kind": row["kind"],
                "document_id": int(row["document_id"]) if row["document_id"] is not None else None,
                "payload_json": normalize_payload(json_loads(row["payload_json"], {})),
                "status": row["status"],
                "attempt_count": int(row["attempt_count"]),
                "max_attempts": int(row["max_attempts"]),
                "leased_by": row["leased_by"],
                "leased_at": row["leased_at"],
                "available_at": row["available_at"],
                "last_error": row["last_error"],
                "completed_at": row["completed_at"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM background_jobs ORDER BY id")
        ],
        "monitoring_rules": [
            {
                "id": int(row["id"]),
                "company_id": int(row["company_id"]),
                "report_id": int(row["report_id"]) if row["report_id"] is not None else None,
                "report_rule_key": row["report_rule_key"],
                "metric_name": row["metric_name"],
                "comparator": row["comparator"],
                "threshold_value": row["threshold_value"],
                "unit": row["unit"],
                "current_value": row["current_value"],
                "source": row["source"],
                "triggered": bool(row["triggered"]),
                "notes": row["notes"],
                "last_checked_at": row["last_checked_at"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in sqlite_query_rows(conn, "SELECT * FROM monitoring_rules ORDER BY id")
        ],
    }


def shadow_rows_from_session(session: Session) -> dict[str, list[dict[str, Any]]]:
    def rows_for(model: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in session.execute(select(model.__table__).order_by(model.__table__.c.id)).mappings().all()]

    return {
        "stages": [
            {
                "id": int(row["id"]),
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "sequence": int(row["sequence"]),
                "is_active": bool(row["is_active"]),
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(Stage)
        ],
        "companies": [
            {
                "id": int(row["id"]),
                "ticker": row["ticker"],
                "name": row["name"],
                "bucket": row["bucket"],
                "current_stage_id": int(row["current_stage_id"]) if row["current_stage_id"] is not None else None,
                "notes": row["notes"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(Company)
        ],
        "templates": [
            {
                "id": int(row["id"]),
                "stage_id": int(row["stage_id"]),
                "name": row["name"],
                "version": int(row["version"]),
                "description": row["description"],
                "markdown": row["markdown"],
                "schema_json": normalize_payload(row["schema_json"] or {}),
                "is_active": bool(row["is_active"]),
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(Template)
        ],
        "reports": [
            {
                "id": int(row["id"]),
                "company_id": int(row["company_id"]),
                "stage_id": int(row["stage_id"]),
                "template_id": int(row["template_id"]),
                "title": row["title"],
                "report_month": row["report_month"],
                "revision": int(row["revision"]),
                "responses_json": normalize_payload(row["responses_json"] or {}),
                "metrics_json": normalize_payload(row["metrics_json"] or {}),
                "section_ratings_json": normalize_payload(row["section_ratings_json"] or {}),
                "data_quality_json": normalize_payload(row["data_quality_json"] or {}),
                "field_sources_json": normalize_payload(row["field_sources_json"] or {}),
                "field_notes_json": normalize_payload(row["field_notes_json"] or {}),
                "field_exceptions_json": normalize_payload(row["field_exceptions_json"] or {}),
                "result": row["result"],
                "summary": row["summary"],
                "watchlist_conditions": row["watchlist_conditions"],
                "watchlist_objective_rules_json": normalize_payload(row["watchlist_objective_rules_json"] or []),
                "watchlist_subjective_rules": row["watchlist_subjective_rules"],
                "archive_red_flags": row["archive_red_flags"],
                "next_action": row["next_action"],
                "review_date": row["review_date"],
                "completed_at": row["completed_at"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(Report)
        ],
        "documents": [
            {
                "id": int(row["id"]),
                "company_id": int(row["company_id"]),
                "report_id": int(row["report_id"]) if row["report_id"] is not None else None,
                "original_name": row["original_name"],
                "stored_name": row["stored_name"],
                "storage_path": row["legacy_storage_path"],
                "mime_type": row["mime_type"],
                "size_bytes": int(row["size_bytes"]),
                "notes": row["notes"],
                "normalized_text_path": row["normalized_text_path"],
                "normalized_status": row["normalized_status"],
                "normalized_format": row["normalized_format"],
                "normalized_method": row["normalized_method"],
                "normalized_notes": row["normalized_notes"],
                "normalized_preview": row["normalized_preview"],
                "normalized_updated_at": row["normalized_updated_at"],
                "uploaded_at": row["uploaded_at"],
            }
            for row in rows_for(Document)
        ],
        "report_sources": [
            {
                "id": int(row["id"]),
                "report_id": int(row["report_id"]),
                "document_id": int(row["document_id"]) if row["document_id"] is not None else None,
                "title": row["title"],
                "capture_kind": row["capture_kind"],
                "source_type": row["source_type"],
                "evidence_grade": row["evidence_grade"],
                "confidence": row["confidence"],
                "tags_json": normalize_payload(row["tags_json"] or []),
                "url": row["url"],
                "canonical_url": row["canonical_url"],
                "link_only_reason": row["link_only_reason"],
                "snapshot_guidance_acknowledged": bool(row["snapshot_guidance_acknowledged"]),
                "capture_state": row["capture_state"],
                "capture_error": row["capture_error"],
                "citation": row["citation"],
                "notes": row["notes"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(ReportSource)
        ],
        "background_jobs": [
            {
                "id": int(row["id"]),
                "kind": row["kind"],
                "document_id": int(row["document_id"]) if row["document_id"] is not None else None,
                "payload_json": normalize_payload(row["payload_json"] or {}),
                "status": row["status"],
                "attempt_count": int(row["attempt_count"]),
                "max_attempts": int(row["max_attempts"]),
                "leased_by": row["leased_by"],
                "leased_at": row["leased_at"],
                "available_at": row["available_at"],
                "last_error": row["last_error"],
                "completed_at": row["completed_at"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(BackgroundJob)
        ],
        "monitoring_rules": [
            {
                "id": int(row["id"]),
                "company_id": int(row["company_id"]),
                "report_id": int(row["report_id"]) if row["report_id"] is not None else None,
                "report_rule_key": row["report_rule_key"],
                "metric_name": row["metric_name"],
                "comparator": row["comparator"],
                "threshold_value": row["threshold_value"],
                "unit": row["unit"],
                "current_value": row["current_value"],
                "source": row["source"],
                "triggered": bool(row["triggered"]),
                "notes": row["notes"],
                "last_checked_at": row["last_checked_at"],
                "created_at": canonical_timestamp(row["created_at"]),
                "updated_at": canonical_timestamp(row["updated_at"]),
            }
            for row in rows_for(MonitoringRule)
        ],
    }


@dataclass(slots=True)
class ShadowSyncResult:
    status: str
    reason: str
    source_fingerprint: str
    manifest_path: Path
    payload: dict[str, Any]


@dataclass(slots=True)
class SnapshotRecord:
    category: str
    request_key: str
    payload: dict[str, Any]
    source_fingerprint: str


class ShadowBackend:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._engine = None
        self._session_factory = None
        self._last_source_fingerprint = ""

    @property
    def enabled(self) -> bool:
        return self.settings.backend_mode in {"shadow", "postgres_verify"}

    @property
    def artifact_root(self) -> Path:
        target = self.settings.contract_dir / "shadow"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _artifact_dir(self, category: str) -> Path:
        target = self.artifact_root / category
        target.mkdir(parents=True, exist_ok=True)
        return target

    def engine(self):
        if self._engine is None:
            self._engine = build_engine(self.settings)
        return self._engine

    def session_factory(self):
        if self._session_factory is None:
            self._session_factory = build_session_factory(self.settings, self.engine())
        return self._session_factory

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self.engine())

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        self._session_factory = None

    def source_fingerprint(self) -> str:
        return self.fingerprint_for(self.settings.sqlite_path, self.settings.upload_root)

    def fingerprint_for(self, sqlite_path: Path, upload_root: Path) -> str:
        db_stat = sqlite_path.stat()
        upload_bits: list[str] = []
        if upload_root.exists():
            for path in sorted(node for node in upload_root.rglob("*") if node.is_file()):
                stat = path.stat()
                upload_bits.append(f"{path.relative_to(upload_root)}:{stat.st_size}:{stat.st_mtime_ns}")
        payload = {
            "db": {
                "path": str(sqlite_path),
                "size_bytes": db_stat.st_size,
                "mtime_ns": db_stat.st_mtime_ns,
            },
            "uploads": upload_bits,
        }
        return hashlib.sha256(json_dump(payload).encode("utf-8")).hexdigest()

    def _reset_shadow_tables(self, session: Session) -> None:
        for model in (EndpointSnapshot, MonitoringRule, BackgroundJob, ReportSource, Document, Report, Template, Company, Stage, Workspace):
            session.execute(delete(model))

    def _import_workspace(self, session: Session, source_rows: dict[str, list[dict[str, Any]]]) -> None:
        timestamps = [
            parse_timestamp(row["created_at"])
            for rows in source_rows.values()
            for row in rows
            if row.get("created_at")
        ]
        updated = [
            parse_timestamp(row["updated_at"])
            for rows in source_rows.values()
            for row in rows
            if row.get("updated_at")
        ]
        created_at = min(timestamps) if timestamps else now_utc()
        updated_at = max(updated) if updated else created_at
        session.add(
            Workspace(
                id=SHADOW_WORKSPACE_ID,
                public_id=SHADOW_WORKSPACE_PUBLIC_ID,
                name=SHADOW_WORKSPACE_NAME,
                slug=SHADOW_WORKSPACE_SLUG,
                created_at=created_at,
                updated_at=updated_at,
            )
        )

    def _import_core_tables(self, session: Session, source_rows: dict[str, list[dict[str, Any]]], *, upload_root: Path) -> None:
        session.bulk_insert_mappings(
            Stage,
            [
                {
                    **row,
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["stages"]
            ],
        )
        session.bulk_insert_mappings(
            Company,
            [
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "public_id": f"company-{row['id']}",
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "slug": slugify(row["ticker"] or row["name"], f"company-{row['id']}"),
                    "bucket": row["bucket"],
                    "current_stage_id": row["current_stage_id"],
                    "notes": row["notes"],
                    "created_by": "",
                    "updated_by": "",
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["companies"]
            ],
        )
        session.bulk_insert_mappings(
            Template,
            [
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "public_id": f"template-{row['id']}",
                    "stage_id": row["stage_id"],
                    "name": row["name"],
                    "version": row["version"],
                    "description": row["description"],
                    "markdown": row["markdown"],
                    "schema_json": row["schema_json"],
                    "is_active": row["is_active"],
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["templates"]
            ],
        )
        session.bulk_insert_mappings(
            Report,
            [
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "public_id": f"report-{row['id']}",
                    "company_id": row["company_id"],
                    "stage_id": row["stage_id"],
                    "template_id": row["template_id"],
                    "title": row["title"],
                    "slug": slugify(row["title"], f"report-{row['id']}"),
                    "report_month": row["report_month"],
                    "revision": row["revision"],
                    "responses_json": row["responses_json"],
                    "metrics_json": row["metrics_json"],
                    "section_ratings_json": row["section_ratings_json"],
                    "data_quality_json": row["data_quality_json"],
                    "field_sources_json": row["field_sources_json"],
                    "field_notes_json": row["field_notes_json"],
                    "field_exceptions_json": row["field_exceptions_json"],
                    "result": row["result"],
                    "summary": row["summary"],
                    "watchlist_conditions": row["watchlist_conditions"],
                    "watchlist_objective_rules_json": row["watchlist_objective_rules_json"],
                    "watchlist_subjective_rules": row["watchlist_subjective_rules"],
                    "archive_red_flags": row["archive_red_flags"],
                    "next_action": row["next_action"],
                    "review_date": row["review_date"],
                    "completed_at": row["completed_at"],
                    "created_by": "",
                    "updated_by": "",
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["reports"]
            ],
        )

        document_rows = []
        for row in source_rows["documents"]:
            storage_path = Path(row["storage_path"])
            normalized_path = Path(row["normalized_text_path"]) if row["normalized_text_path"] else None
            document_rows.append(
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "public_id": f"document-{row['id']}",
                    "company_id": row["company_id"],
                    "report_id": row["report_id"],
                    "original_name": row["original_name"],
                    "stored_name": row["stored_name"],
                    "storage_key": relative_storage_key(upload_root, row["storage_path"], row["stored_name"]),
                    "legacy_storage_path": row["storage_path"],
                    "mime_type": row["mime_type"],
                    "size_bytes": row["size_bytes"],
                    "content_sha256": file_sha256(storage_path) if storage_path.exists() else "",
                    "notes": row["notes"],
                    "normalized_storage_key": relative_storage_key(upload_root, row["normalized_text_path"], normalized_path.name if normalized_path else ""),
                    "normalized_text_path": row["normalized_text_path"],
                    "normalized_status": row["normalized_status"],
                    "normalized_format": row["normalized_format"],
                    "normalized_method": row["normalized_method"],
                    "normalized_notes": row["normalized_notes"],
                    "normalized_preview": row["normalized_preview"],
                    "normalized_updated_at": row["normalized_updated_at"],
                    "uploaded_at": row["uploaded_at"],
                }
            )
        session.bulk_insert_mappings(Document, document_rows)

        session.bulk_insert_mappings(
            ReportSource,
            [
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "report_id": row["report_id"],
                    "document_id": row["document_id"],
                    "title": row["title"],
                    "capture_kind": row["capture_kind"],
                    "source_type": row["source_type"],
                    "evidence_grade": row["evidence_grade"],
                    "confidence": row["confidence"],
                    "tags_json": row["tags_json"],
                    "url": row["url"],
                    "canonical_url": row["canonical_url"],
                    "link_only_reason": row["link_only_reason"],
                    "snapshot_guidance_acknowledged": row["snapshot_guidance_acknowledged"],
                    "capture_state": row["capture_state"],
                    "capture_error": row["capture_error"],
                    "citation": row["citation"],
                    "notes": row["notes"],
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["report_sources"]
            ],
        )
        session.bulk_insert_mappings(
            BackgroundJob,
            [
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "kind": row["kind"],
                    "document_id": row["document_id"],
                    "payload_json": row["payload_json"],
                    "status": row["status"],
                    "attempt_count": row["attempt_count"],
                    "max_attempts": row["max_attempts"],
                    "leased_by": row["leased_by"],
                    "leased_at": row["leased_at"],
                    "available_at": row["available_at"],
                    "last_error": row["last_error"],
                    "completed_at": row["completed_at"],
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["background_jobs"]
            ],
        )
        session.bulk_insert_mappings(
            MonitoringRule,
            [
                {
                    "id": row["id"],
                    "workspace_id": SHADOW_WORKSPACE_ID,
                    "company_id": row["company_id"],
                    "report_id": row["report_id"],
                    "report_rule_key": row["report_rule_key"],
                    "metric_name": row["metric_name"],
                    "comparator": row["comparator"],
                    "threshold_value": row["threshold_value"],
                    "unit": row["unit"],
                    "current_value": row["current_value"],
                    "source": row["source"],
                    "triggered": row["triggered"],
                    "notes": row["notes"],
                    "last_checked_at": row["last_checked_at"],
                    "created_at": parse_timestamp(row["created_at"]),
                    "updated_at": parse_timestamp(row["updated_at"]),
                }
                for row in source_rows["monitoring_rules"]
            ],
        )

    def _document_file_checks(self, source_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for row in source_rows["documents"]:
            storage_path = Path(row["storage_path"])
            normalized_path = Path(row["normalized_text_path"]) if row["normalized_text_path"] else None
            checks.append(
                {
                    "document_id": row["id"],
                    "storage_path": row["storage_path"],
                    "storage_sha256": file_sha256(storage_path) if storage_path.exists() else "",
                    "normalized_text_path": row["normalized_text_path"],
                    "normalized_sha256": file_sha256(normalized_path) if normalized_path and normalized_path.exists() else "",
                }
            )
        return checks

    def sync_from_sqlite_snapshot(self, sqlite_path: Path, upload_root: Path, reason: str) -> ShadowSyncResult | None:
        if not self.enabled:
            return None
        for directory in ("read-parity", "write-parity", "worker-parity", "fallback-events", "contract-mismatches"):
            self._artifact_dir(directory)
        source_fingerprint = self.fingerprint_for(sqlite_path, upload_root)
        self.ensure_schema()
        sqlite_conn = legacy_db.connect(sqlite_path)
        try:
            source_rows = canonical_sqlite_rows(sqlite_conn)
        finally:
            sqlite_conn.close()
        session = self.session_factory()()
        try:
            self._reset_shadow_tables(session)
            self._import_workspace(session, source_rows)
            self._import_core_tables(session, source_rows, upload_root=upload_root)
            session.commit()
            shadow_rows = shadow_rows_from_session(session)
        finally:
            session.close()
        comparison = self._compare_state(source_rows, shadow_rows)
        manifest = {
            "mode": "shadow-import",
            "backend_mode": self.settings.backend_mode,
            "reason": reason,
            "shadow_database_url": self.settings.postgres_url,
            "source_fingerprint": source_fingerprint,
            "status": comparison["status"],
            "tables": comparison["tables"],
            "diffs": comparison["diffs"],
            "document_file_checks": self._document_file_checks(source_rows),
            "upload_files": upload_tree_manifest(upload_root),
            "written_at": now_utc().isoformat(),
        }
        manifest_path = self._write_json_artifact(self.artifact_root, "migration-import-manifest", manifest)
        compatibility_path = self.settings.contract_dir / "migration-dry-run.json"
        compatibility_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return ShadowSyncResult(
            status=str(manifest["status"]),
            reason=reason,
            source_fingerprint=source_fingerprint,
            manifest_path=manifest_path,
            payload=manifest,
        )

    def _compare_state(self, source_rows: dict[str, list[dict[str, Any]]], shadow_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        tables: dict[str, Any] = {}
        diffs: list[dict[str, Any]] = []
        for table in TABLE_ORDER:
            source_table = normalize_payload(source_rows[table])
            shadow_table = normalize_payload(shadow_rows[table])
            table_diffs = diff_values(source_table, shadow_table)
            tables[table] = {
                "source_count": len(source_table),
                "shadow_count": len(shadow_table),
                "source_digest": table_digest(source_table),
                "shadow_digest": table_digest(shadow_table),
                "status": "ok" if not table_diffs else "diff",
                "diff_count": len(table_diffs),
                "diffs": table_diffs[:50],
            }
            for item in table_diffs[:20]:
                diffs.append({"table": table, **item})
        return {
            "status": "ok" if not diffs else "diff",
            "tables": tables,
            "diffs": diffs,
        }

    def record_state_reconciliation(
        self,
        *,
        category: str,
        request_key: str,
        sqlite_path: Path | None = None,
        upload_root: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        source_sqlite = sqlite_path or self.settings.sqlite_path
        source_upload_root = upload_root or self.settings.upload_root
        conn = legacy_db.connect(source_sqlite)
        try:
            source_rows = canonical_sqlite_rows(conn)
        finally:
            conn.close()
        session = self.session_factory()()
        try:
            shadow_rows = shadow_rows_from_session(session)
        finally:
            session.close()
        comparison = self._compare_state(source_rows, shadow_rows)
        payload = {
            "category": category,
            "request_key": request_key,
            "sqlite_path": str(source_sqlite),
            "upload_root": str(source_upload_root),
            "source_fingerprint": self.fingerprint_for(source_sqlite, source_upload_root),
            "written_at": now_utc().isoformat(),
            **comparison,
        }
        path = self._write_json_artifact(
            self._artifact_dir("state-reconciliations"),
            f"{slugify(category, 'state')}-{short_hash(request_key)}",
            payload,
        )
        return path, payload

    def _write_json_artifact(self, directory: Path, stem: str, payload: dict[str, Any]) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _append_promotion_summary(
        self,
        *,
        category: str,
        policy: str,
        served_by: str,
        fallback_used: bool,
        request_key: str,
        artifact_path: Path | None = None,
    ) -> Path:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        summary_path = self.artifact_root / "promotion-summary.json"
        if summary_path.exists():
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            payload = {"updated_at": "", "categories": {}}
        categories = payload.setdefault("categories", {})
        entry = categories.setdefault(
            category,
            {
                "policy": policy,
                "served_by": {"legacy": 0, "postgres": 0},
                "fallbacks": 0,
                "requests": 0,
                "last_request_key": "",
                "last_artifact_path": "",
            },
        )
        entry["policy"] = policy
        entry["served_by"][served_by] = int(entry["served_by"].get(served_by, 0)) + 1
        entry["requests"] = int(entry.get("requests", 0)) + 1
        if fallback_used:
            entry["fallbacks"] = int(entry.get("fallbacks", 0)) + 1
        entry["last_request_key"] = request_key
        entry["last_artifact_path"] = str(artifact_path) if artifact_path else ""
        payload["updated_at"] = now_utc().isoformat()
        summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary_path

    def sync_from_source(self, reason: str, force: bool = False) -> ShadowSyncResult | None:
        if not self.enabled:
            return None
        for directory in (
            "read-parity",
            "write-parity",
            "worker-parity",
            "fallback-events",
            "contract-mismatches",
            "state-reconciliations",
            "integrity",
        ):
            self._artifact_dir(directory)
        source_fingerprint = self.source_fingerprint()
        latest_path = self.artifact_root / "migration-import-manifest.json"
        if not force and latest_path.exists():
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
            manifest_fingerprint = str(payload.get("source_fingerprint") or "")
            if source_fingerprint == manifest_fingerprint or source_fingerprint == self._last_source_fingerprint:
                self._last_source_fingerprint = source_fingerprint
                return ShadowSyncResult(
                    status=str(payload.get("status") or "ok"),
                    reason=reason,
                    source_fingerprint=source_fingerprint,
                    manifest_path=latest_path,
                    payload=payload,
                )

        result = self.sync_from_sqlite_snapshot(self.settings.sqlite_path, self.settings.upload_root, reason)
        self._last_source_fingerprint = source_fingerprint
        return result

    def _snapshot_upsert(self, category: str, request_key: str, payload: dict[str, Any], source_fingerprint: str) -> dict[str, Any]:
        session = self.session_factory()()
        try:
            snapshot = session.execute(select(EndpointSnapshot).where(EndpointSnapshot.request_key == request_key)).scalar_one_or_none()
            timestamp = now_utc()
            if snapshot is None:
                snapshot = EndpointSnapshot(
                    category=category,
                    request_key=request_key,
                    payload_json=payload,
                    source_fingerprint=source_fingerprint,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(snapshot)
            else:
                snapshot.category = category
                snapshot.payload_json = payload
                snapshot.source_fingerprint = source_fingerprint
                snapshot.updated_at = timestamp
            session.commit()
            stored = session.execute(select(EndpointSnapshot).where(EndpointSnapshot.request_key == request_key)).scalar_one()
            return normalize_payload(stored.payload_json or {})
        finally:
            session.close()

    def load_snapshot(self, request_key: str) -> dict[str, Any] | None:
        record = self.load_snapshot_record(request_key)
        return record.payload if record else None

    def load_snapshot_record(self, request_key: str) -> SnapshotRecord | None:
        session = self.session_factory()()
        try:
            snapshot = session.execute(select(EndpointSnapshot).where(EndpointSnapshot.request_key == request_key)).scalar_one_or_none()
            if snapshot is None:
                return None
            return SnapshotRecord(
                category=snapshot.category,
                request_key=snapshot.request_key,
                payload=normalize_payload(snapshot.payload_json or {}),
                source_fingerprint=snapshot.source_fingerprint,
            )
        finally:
            session.close()

    def record_contract_mismatch(
        self,
        *,
        category: str,
        request_key: str,
        policy: str,
        legacy_payload: dict[str, Any],
        postgres_payload: dict[str, Any],
        diffs: list[dict[str, Any]],
    ) -> Path:
        payload = {
            "category": category,
            "request_key": request_key,
            "policy": policy,
            "status": "diff",
            "legacy_digest": table_digest([normalize_payload(strip_transport_fields(legacy_payload))]),
            "postgres_digest": table_digest([normalize_payload(strip_transport_fields(postgres_payload))]),
            "diff_count": len(diffs),
            "diffs": diffs[:100],
            "written_at": now_utc().isoformat(),
        }
        return self._write_json_artifact(
            self._artifact_dir("contract-mismatches"),
            f"{slugify(category, 'contract-mismatch')}-{short_hash(request_key)}",
            payload,
        )

    def record_fallback_event(
        self,
        *,
        category: str,
        request_key: str,
        policy: str,
        reason: str,
        primary_backend: str,
        detail: str = "",
        artifact_path: Path | None = None,
    ) -> Path:
        payload = {
            "category": category,
            "request_key": request_key,
            "policy": policy,
            "primary_backend": primary_backend,
            "served_by": "legacy",
            "fallback_used": True,
            "cutback_eligible": True,
            "reason": reason,
            "detail": detail,
            "linked_artifact_path": str(artifact_path) if artifact_path else "",
            "written_at": now_utc().isoformat(),
        }
        path = self._write_json_artifact(
            self._artifact_dir("fallback-events"),
            f"{slugify(category, 'fallback')}-{short_hash(request_key)}",
            payload,
        )
        self._append_promotion_summary(
            category=category,
            policy=policy,
            served_by="legacy",
            fallback_used=True,
            request_key=request_key,
            artifact_path=path,
        )
        return path

    def record_promotion_result(
        self,
        *,
        category: str,
        request_key: str,
        policy: str,
        served_by: str,
        fallback_used: bool,
        artifact_path: Path | None = None,
    ) -> Path:
        return self._append_promotion_summary(
            category=category,
            policy=policy,
            served_by=served_by,
            fallback_used=fallback_used,
            request_key=request_key,
            artifact_path=artifact_path,
        )

    def observe_read(self, category: str, request_key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        sync_result = self.sync_from_source(reason=f"read:{category}", force=False)
        normalized = normalize_payload(strip_transport_fields(payload))
        stored = self._snapshot_upsert(category, request_key, normalized, sync_result.source_fingerprint if sync_result else "")
        diffs = diff_values(normalized, stored)
        artifact = {
            "kind": "read",
            "category": category,
            "request_key": request_key,
            "status": "ok" if not diffs and (sync_result is None or sync_result.status == "ok") else "diff",
            "source_fingerprint": sync_result.source_fingerprint if sync_result else "",
            "state_manifest_path": str(sync_result.manifest_path) if sync_result else "",
            "payload_digest": table_digest([normalized]),
            "snapshot_digest": table_digest([stored]),
            "diffs": diffs[:50],
            "written_at": now_utc().isoformat(),
        }
        artifact_path = self._write_json_artifact(
            self._artifact_dir("read-parity"),
            f"{slugify(category, 'read')}-{short_hash(request_key)}",
            artifact,
        )
        artifact["artifact_path"] = str(artifact_path)
        return artifact

    def observe_write(self, category: str, request_key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        sync_result = self.sync_from_source(reason=f"write:{category}", force=True)
        normalized = normalize_payload(strip_transport_fields(payload))
        stored = self._snapshot_upsert(category, request_key, normalized, sync_result.source_fingerprint if sync_result else "")
        diffs = diff_values(normalized, stored)
        artifact = {
            "kind": "write",
            "category": category,
            "request_key": request_key,
            "status": "ok" if not diffs and (sync_result is None or sync_result.status == "ok") else "diff",
            "source_fingerprint": sync_result.source_fingerprint if sync_result else "",
            "state_manifest_path": str(sync_result.manifest_path) if sync_result else "",
            "payload_digest": table_digest([normalized]),
            "snapshot_digest": table_digest([stored]),
            "diffs": diffs[:50],
            "written_at": now_utc().isoformat(),
        }
        artifact_path = self._write_json_artifact(
            self._artifact_dir("write-parity"),
            f"{slugify(category, 'write')}-{short_hash(request_key)}",
            artifact,
        )
        artifact["artifact_path"] = str(artifact_path)
        return artifact

    def observe_worker_cycle(self, category: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        sync_result = self.sync_from_source(reason=f"worker:{category}", force=True)
        artifact = {
            "kind": "worker",
            "category": category,
            "status": sync_result.status if sync_result else "ok",
            "source_fingerprint": sync_result.source_fingerprint if sync_result else "",
            "state_manifest_path": str(sync_result.manifest_path) if sync_result else "",
            "written_at": now_utc().isoformat(),
        }
        artifact_path = self._write_json_artifact(
            self._artifact_dir("worker-parity"),
            f"{slugify(category, 'worker')}-{short_hash(category)}",
            artifact,
        )
        artifact["artifact_path"] = str(artifact_path)
        return artifact
