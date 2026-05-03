from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Callable

from sqlalchemy import func
from sqlalchemy import select

from app.db.models import Company
from app.db.models import Document
from app.db.models import MonitoringRule
from app.db.models import Report
from app.db.models import BackgroundJob
from app.db.models import AgentRun
from app.db.models import AgentRunStep
from app.db.models import AgentToolCall
from app.db.models import ReportSectionModule
from app.db.models import ReportSource
from app.db.models import Stage
from app.db.models import Template
from app.db.models import TemplateSectionModule
from app.integrity import assert_no_critical_issues
from app.integrity import audit_report_record
from app.integrity import audit_template_record
from app.native_authority import NativeAuthorityStore
from app.shadow import ShadowBackend
from app.shadow import now_utc
from app.shadow import slugify

from funnel_app import db as legacy_db

LEGACY_TABLE_COLUMNS: dict[str, list[str]] = {
    "stages": ["id", "key", "name", "description", "sequence", "is_active", "created_at", "updated_at"],
    "companies": ["id", "ticker", "name", "bucket", "current_stage_id", "notes", "created_at", "updated_at"],
    "templates": [
        "id",
        "stage_id",
        "name",
        "version",
        "description",
        "markdown",
        "schema_json",
        "is_active",
        "created_at",
        "updated_at",
    ],
    "reports": [
        "id",
        "company_id",
        "stage_id",
        "template_id",
        "title",
        "report_month",
        "revision",
        "responses_json",
        "metrics_json",
        "section_ratings_json",
        "data_quality_json",
        "field_sources_json",
        "field_notes_json",
        "field_exceptions_json",
        "result",
        "summary",
        "watchlist_conditions",
        "watchlist_objective_rules_json",
        "watchlist_subjective_rules",
        "archive_red_flags",
        "next_action",
        "review_date",
        "completed_at",
        "created_at",
        "updated_at",
    ],
    "template_section_modules": [
        "id",
        "template_id",
        "stage_key",
        "section_id",
        "section_title",
        "section_path",
        "section_ordinal",
        "schema_version",
        "module_json",
        "created_at",
        "updated_at",
    ],
    "report_section_modules": [
        "id",
        "report_id",
        "template_id",
        "stage_key",
        "section_id",
        "section_title",
        "section_path",
        "section_ordinal",
        "revision",
        "schema_version",
        "module_json",
        "created_at",
        "updated_at",
    ],
    "documents": [
        "id",
        "company_id",
        "report_id",
        "original_name",
        "stored_name",
        "storage_path",
        "mime_type",
        "size_bytes",
        "notes",
        "normalized_text_path",
        "normalized_status",
        "normalized_format",
        "normalized_method",
        "normalized_notes",
        "normalized_preview",
        "normalized_updated_at",
        "uploaded_at",
    ],
    "report_sources": [
        "id",
        "report_id",
        "document_id",
        "title",
        "capture_kind",
        "source_type",
        "evidence_grade",
        "confidence",
        "tags_json",
        "url",
        "canonical_url",
        "link_only_reason",
        "snapshot_guidance_acknowledged",
        "capture_state",
        "capture_error",
        "citation",
        "notes",
        "created_at",
        "updated_at",
    ],
    "background_jobs": [
        "id",
        "kind",
        "document_id",
        "payload_json",
        "status",
        "attempt_count",
        "max_attempts",
        "leased_by",
        "leased_at",
        "available_at",
        "last_error",
        "completed_at",
        "created_at",
        "updated_at",
    ],
    "monitoring_rules": [
        "id",
        "company_id",
        "report_id",
        "report_rule_key",
        "metric_name",
        "comparator",
        "threshold_value",
        "unit",
        "current_value",
        "source",
        "triggered",
        "notes",
        "last_checked_at",
        "created_at",
        "updated_at",
    ],
    "agent_runs": [
        "id",
        "report_id",
        "section_id",
        "run_kind",
        "status",
        "orchestrator",
        "mcp_session_id",
        "prompt_name",
        "state_json",
        "created_at",
        "updated_at",
        "completed_at",
    ],
    "agent_run_steps": [
        "id",
        "run_id",
        "step_key",
        "status",
        "input_json",
        "output_json",
        "error",
        "created_at",
        "updated_at",
    ],
    "agent_tool_calls": [
        "id",
        "run_id",
        "step_id",
        "tool_name",
        "arguments_json",
        "result_json",
        "status",
        "request_id",
        "created_at",
        "updated_at",
    ],
}

SOURCE_STRING_COLUMNS: dict[str, list[str]] = {
    "stages": ["created_at", "updated_at"],
    "companies": ["created_at", "updated_at"],
    "templates": ["created_at", "updated_at"],
    "reports": ["created_at", "updated_at", "completed_at"],
    "template_section_modules": ["created_at", "updated_at"],
    "report_section_modules": ["created_at", "updated_at"],
    "documents": ["uploaded_at", "normalized_updated_at"],
    "report_sources": ["created_at", "updated_at"],
    "background_jobs": ["created_at", "updated_at", "leased_at", "available_at", "completed_at"],
    "monitoring_rules": ["created_at", "updated_at", "last_checked_at"],
    "agent_runs": ["created_at", "updated_at", "completed_at"],
    "agent_run_steps": ["created_at", "updated_at"],
    "agent_tool_calls": ["created_at", "updated_at"],
}


def iso_utc(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="seconds")


def json_string(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PostgresCompatibilityStore:
    def __init__(self, shadow: ShadowBackend):
        self.shadow = shadow
        self._native = NativeAuthorityStore(shadow)
        self.native_authority = True

    @property
    def settings(self):
        return self.shadow.settings

    def ensure_synced(self, *, force: bool = False):
        return self.shadow.sync_from_source("postgres-services", force=force)

    def _export_rows(self) -> dict[str, list[dict[str, Any]]]:
        session = self.shadow.session_factory()()
        try:
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
                        "is_active": 1 if row["is_active"] else 0,
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
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
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
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
                        "schema_json": json_string(row["schema_json"] or {}),
                        "is_active": 1 if row["is_active"] else 0,
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
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
                        "responses_json": json_string(row["responses_json"] or {}),
                        "metrics_json": json_string(row["metrics_json"] or {}),
                        "section_ratings_json": json_string(row["section_ratings_json"] or {}),
                        "data_quality_json": json_string(row["data_quality_json"] or {}),
                        "field_sources_json": json_string(row["field_sources_json"] or {}),
                        "field_notes_json": json_string(row["field_notes_json"] or {}),
                        "field_exceptions_json": json_string(row["field_exceptions_json"] or {}),
                        "result": row["result"],
                        "summary": row["summary"],
                        "watchlist_conditions": row["watchlist_conditions"],
                        "watchlist_objective_rules_json": json_string(row["watchlist_objective_rules_json"] or []),
                        "watchlist_subjective_rules": row["watchlist_subjective_rules"],
                        "archive_red_flags": row["archive_red_flags"],
                        "next_action": row["next_action"],
                        "review_date": row["review_date"],
                        "completed_at": row["completed_at"],
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(Report)
                ],
                "template_section_modules": [
                    {
                        "id": int(row["id"]),
                        "template_id": int(row["template_id"]),
                        "stage_key": row["stage_key"],
                        "section_id": row["section_id"],
                        "section_title": row["section_title"],
                        "section_path": row["section_path"],
                        "section_ordinal": int(row["section_ordinal"]),
                        "schema_version": int(row["schema_version"]),
                        "module_json": json_string(row["module_json"] or {}),
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(TemplateSectionModule)
                ],
                "report_section_modules": [
                    {
                        "id": int(row["id"]),
                        "report_id": int(row["report_id"]),
                        "template_id": int(row["template_id"]),
                        "stage_key": row["stage_key"],
                        "section_id": row["section_id"],
                        "section_title": row["section_title"],
                        "section_path": row["section_path"],
                        "section_ordinal": int(row["section_ordinal"]),
                        "revision": int(row["revision"]),
                        "schema_version": int(row["schema_version"]),
                        "module_json": json_string(row["module_json"] or {}),
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(ReportSectionModule)
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
                        "tags_json": json_string(row["tags_json"] or []),
                        "url": row["url"],
                        "canonical_url": row["canonical_url"],
                        "link_only_reason": row["link_only_reason"],
                        "snapshot_guidance_acknowledged": 1 if row["snapshot_guidance_acknowledged"] else 0,
                        "capture_state": row["capture_state"],
                        "capture_error": row["capture_error"],
                        "citation": row["citation"],
                        "notes": row["notes"],
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(ReportSource)
                ],
                "background_jobs": [
                    {
                        "id": int(row["id"]),
                        "kind": row["kind"],
                        "document_id": int(row["document_id"]) if row["document_id"] is not None else None,
                        "payload_json": json_string(row["payload_json"] or {}),
                        "status": row["status"],
                        "attempt_count": int(row["attempt_count"]),
                        "max_attempts": int(row["max_attempts"]),
                        "leased_by": row["leased_by"],
                        "leased_at": row["leased_at"],
                        "available_at": row["available_at"],
                        "last_error": row["last_error"],
                        "completed_at": row["completed_at"],
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
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
                        "triggered": 1 if row["triggered"] else 0,
                        "notes": row["notes"],
                        "last_checked_at": row["last_checked_at"],
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(MonitoringRule)
                ],
                "agent_runs": [
                    {
                        "id": int(row["id"]),
                        "report_id": int(row["report_id"]) if row["report_id"] is not None else None,
                        "section_id": row["section_id"],
                        "run_kind": row["run_kind"],
                        "status": row["status"],
                        "orchestrator": row["orchestrator"],
                        "mcp_session_id": row["mcp_session_id"],
                        "prompt_name": row["prompt_name"],
                        "state_json": json_string(row["state_json"] or {}),
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                        "completed_at": row["completed_at"],
                    }
                    for row in rows_for(AgentRun)
                ],
                "agent_run_steps": [
                    {
                        "id": int(row["id"]),
                        "run_id": int(row["run_id"]),
                        "step_key": row["step_key"],
                        "status": row["status"],
                        "input_json": json_string(row["input_json"] or {}),
                        "output_json": json_string(row["output_json"] or {}),
                        "error": row["error"],
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(AgentRunStep)
                ],
                "agent_tool_calls": [
                    {
                        "id": int(row["id"]),
                        "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
                        "step_id": int(row["step_id"]) if row["step_id"] is not None else None,
                        "tool_name": row["tool_name"],
                        "arguments_json": json_string(row["arguments_json"] or {}),
                        "result_json": json_string(row["result_json"] or {}),
                        "status": row["status"],
                        "request_id": row["request_id"],
                        "created_at": iso_utc(row["created_at"]),
                        "updated_at": iso_utc(row["updated_at"]),
                    }
                    for row in rows_for(AgentToolCall)
                ],
            }
        finally:
            session.close()

    def _view_root(self) -> Path:
        root = self.settings.contract_dir / "shadow" / "pg-legacy-views"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _view_path(self, fingerprint: str) -> Path:
        return self._view_root() / f"{fingerprint}.db"

    def _live_storage_root(self) -> Path:
        root = self.settings.contract_dir / "shadow" / "pg-storage"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _prepare_live_storage_root(self) -> Path:
        root = self._live_storage_root()
        shutil.rmtree(root, ignore_errors=True)
        if self.settings.upload_root.exists():
            shutil.copytree(self.settings.upload_root, root)
        else:
            root.mkdir(parents=True, exist_ok=True)
        return root

    def _live_storage_path(self, current_path: str, live_upload_root: Path) -> str:
        raw = str(current_path or "").strip()
        if not raw:
            return ""
        candidate = Path(raw)
        try:
            relative = candidate.resolve().relative_to(self.settings.upload_root.resolve())
        except Exception:
            try:
                candidate.resolve().relative_to(live_upload_root.resolve())
                return str(candidate)
            except Exception:
                return str(candidate)
        return str((live_upload_root / relative).resolve())

    def _repoint_document_paths(self, db_path: Path, live_upload_root: Path) -> None:
        conn = legacy_db.connect(db_path)
        try:
            rows = conn.execute("SELECT id, storage_path, normalized_text_path FROM documents").fetchall()
            for row in rows:
                storage_path = self._live_storage_path(str(row["storage_path"] or ""), live_upload_root)
                normalized_text_path = self._live_storage_path(str(row["normalized_text_path"] or ""), live_upload_root)
                conn.execute(
                    """
                    UPDATE documents
                    SET storage_path = ?, normalized_text_path = ?
                    WHERE id = ?
                    """,
                    (storage_path, normalized_text_path, int(row["id"])),
                )
            conn.commit()
        finally:
            conn.close()

    def _overlay_source_strings(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        conn = legacy_db.connect(self.settings.sqlite_path)
        try:
            for table, columns in SOURCE_STRING_COLUMNS.items():
                indexed = {int(row["id"]): row for row in rows[table] if row.get("id") is not None}
                if not indexed:
                    continue
                ids = sorted(indexed)
                placeholders = ", ".join("?" for _ in ids)
                raw_rows = conn.execute(
                    f"SELECT id, {', '.join(columns)} FROM {table} WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
                for raw in raw_rows:
                    target = indexed.get(int(raw["id"]))
                    if not target:
                        continue
                    for column in columns:
                        if raw[column] not in (None, ""):
                            target[column] = raw[column]
        finally:
            conn.close()

    def _rebuild_legacy_view(self, path: Path, *, overlay_source_strings: bool) -> None:
        if path.exists():
            path.unlink()
        shutil.copy2(self.settings.sqlite_path, path)
        rows = self._export_rows()
        if overlay_source_strings:
            self._overlay_source_strings(rows)
        conn = legacy_db.connect(path)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            for table in reversed(list(LEGACY_TABLE_COLUMNS)):
                conn.execute(f"DELETE FROM {table}")
            for table, columns in LEGACY_TABLE_COLUMNS.items():
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(columns)
                values = [
                    tuple(row.get(column) for column in columns)
                    for row in rows[table]
                ]
                if values:
                    conn.executemany(
                        f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                        values,
                    )
            conn.commit()
        finally:
            conn.close()

    def ensure_legacy_view(self) -> Path:
        sync_result = self.ensure_synced(force=False)
        fingerprint = sync_result.source_fingerprint if sync_result else self.shadow.source_fingerprint()
        path = self._view_path(fingerprint)
        self._rebuild_legacy_view(path, overlay_source_strings=True)
        return path

    def live_legacy_view(self) -> Path:
        path = self._view_root() / "_live.db"
        self._rebuild_legacy_view(path, overlay_source_strings=False)
        return path

    def _canonicalize_live_paths(self, value: Any, live_upload_root: Path) -> Any:
        if isinstance(value, dict):
            rewritten: dict[str, Any] = {}
            for key, entry in value.items():
                if key in {"storage_path", "normalized_text_path", "legacy_storage_path"} and isinstance(entry, str) and entry:
                    try:
                        relative = Path(entry).resolve().relative_to(live_upload_root.resolve())
                        rewritten[key] = str((self.settings.upload_root / relative).resolve())
                    except Exception:
                        rewritten[key] = entry
                    continue
                rewritten[key] = self._canonicalize_live_paths(entry, live_upload_root)
            return rewritten
        if isinstance(value, list):
            return [self._canonicalize_live_paths(item, live_upload_root) for item in value]
        return value

    @contextmanager
    def open_legacy_view(self, *, live: bool = False):
        path = self.live_legacy_view() if live else self.ensure_legacy_view()
        conn = legacy_db.connect(path)
        try:
            yield conn
        finally:
            conn.close()

    def _mutate_live_state(
        self,
        reason: str,
        mutator: Callable[[Any, Path], dict[str, Any]],
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        live_db_path = self.live_legacy_view()
        live_upload_root = self._prepare_live_storage_root()
        conn = legacy_db.connect(live_db_path)
        try:
            payload = mutator(conn, live_upload_root)
        finally:
            conn.close()
        if persist:
            self.shadow.sync_from_sqlite_snapshot(live_db_path, live_upload_root, reason)
        return self._canonicalize_live_paths(payload, live_upload_root)

    def _validate_template_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        template = payload.get("template") or {}
        issues = audit_template_record(template)
        assert_no_critical_issues(issues, context=f"template {template.get('id', 'unknown')}")
        return payload

    def _validate_report_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        report = payload.get("report") or {}
        issues = audit_report_record(report)
        assert_no_critical_issues(issues, context=f"report {report.get('id', 'unknown')}")
        return payload

    def bootstrap(self) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            return {
                "dashboard": legacy_db.dashboard(conn),
                "settings_summary": legacy_db.settings_summary(conn),
                "stages": legacy_db.list_stages(conn),
                "buckets": legacy_db.BUCKETS,
                "report_actions": legacy_db.REPORT_ACTIONS,
            }

    def stages(self) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            return {"stages": legacy_db.list_stages(conn)}

    def templates(self) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            return {"templates": legacy_db.list_templates(conn)}

    def template(self, template_id: int) -> dict[str, Any]:
        return self._validate_template_payload(self.raw_template(template_id))

    def raw_template(self, template_id: int, *, live: bool = False) -> dict[str, Any]:
        with self.open_legacy_view(live=live) as conn:
            template = legacy_db.get_template(conn, template_id)
            if not template:
                raise KeyError("Template not found.")
            return {"template": template}

    def template_live(self, template_id: int) -> dict[str, Any]:
        return self._validate_template_payload(self.raw_template(template_id, live=True))

    def companies(
        self,
        *,
        bucket: str | None,
        stage_id: int | None,
        search: str | None,
        order: str | None,
        page: int,
        per_page: int,
    ) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            return {
                "companies": legacy_db.list_companies(
                    conn,
                    bucket=bucket,
                    stage_id=stage_id,
                    search=search,
                    order=order,
                    page=page,
                    per_page=per_page,
                ),
                "total": legacy_db.count_companies(conn, bucket=bucket, stage_id=stage_id, search=search),
                "page": page,
                "per_page": per_page,
            }

    def company(self, company_id: int) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            company = legacy_db.get_company(conn, company_id)
            if not company:
                raise KeyError("Company not found.")
            return {"company": company}

    def company_live(self, company_id: int) -> dict[str, Any]:
        with self.open_legacy_view(live=True) as conn:
            company = legacy_db.get_company(conn, company_id)
            if not company:
                raise KeyError("Company not found.")
            return {"company": company}

    def monitoring(self) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            return {"rules": legacy_db.list_monitoring_rules(conn, bucket="monitoring")}

    def reports(
        self,
        *,
        stage_id: int | None,
        result: str | None,
        search: str | None,
        include_drafts: bool,
        order: str | None,
        page: int,
        per_page: int,
    ) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            return {
                "reports": legacy_db.list_report_summaries(
                    conn,
                    stage_id=stage_id,
                    result=result,
                    search=search,
                    include_drafts=include_drafts,
                    order=order or "completed_desc",
                    page=page,
                    per_page=per_page,
                    include_company=True,
                    include_completed_at=True,
                ),
                "total": legacy_db.count_reports(
                    conn,
                    stage_id=stage_id,
                    result=result,
                    search=search,
                    include_drafts=include_drafts,
                ),
                "page": page,
                "per_page": per_page,
            }

    def raw_report(self, report_id: int, *, live: bool = False) -> dict[str, Any]:
        with self.open_legacy_view(live=live) as conn:
            report = legacy_db.get_report(conn, report_id)
            if not report:
                raise KeyError("Report not found.")
            return {"report": report}

    def report(self, report_id: int) -> dict[str, Any]:
        return self._validate_report_payload(self.raw_report(report_id))

    def create_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._validate_report_payload(
            self._mutate_live_state(
                "postgres-create-report",
                lambda conn, _upload_root: {"report": legacy_db.create_report(conn, payload)},
            )
        )

    def preview_report(self, report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._mutate_live_state(
            "postgres-preview-report",
            lambda conn, _upload_root: legacy_db.preview_report_completion(conn, report_id, payload),
            persist=False,
        )

    def update_report(self, report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._validate_report_payload(
            self._mutate_live_state(
                "postgres-update-report",
                lambda conn, _upload_root: {"report": legacy_db.update_report(conn, report_id, payload)},
            )
        )

    def delete_report(self, report_id: int) -> dict[str, Any]:
        return self._mutate_live_state(
            "postgres-delete-report",
            lambda conn, _upload_root: {"company": legacy_db.delete_report(conn, report_id)},
        )

    def document_status(self, document_id: int) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            document = legacy_db.document_status_record(conn, document_id)
            if not document:
                raise KeyError("Document not found.")
            return {"document": document}

    def document_record(self, document_id: int) -> dict[str, Any]:
        with self.open_legacy_view() as conn:
            document = legacy_db.get_document(conn, document_id)
            if not document:
                raise KeyError("Document not found.")
            return {"document": document}

    def upload_documents(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = list(payload.get("files") or [])
        if not files:
            raise ValueError("At least one file is required.")
        company_id = int(payload["company_id"])
        report_id = int(payload["report_id"]) if payload.get("report_id") else None
        notes = str(payload.get("notes") or "")
        return self._mutate_live_state(
            "postgres-upload-documents",
            lambda conn, upload_root: {
                "documents": [
                    legacy_db.save_document(
                        conn,
                        upload_root,
                        company_id,
                        item["filename"],
                        item["content"],
                        report_id=report_id,
                        notes=notes,
                        mime_type=item.get("mime_type", ""),
                    )
                    for item in files
                ]
            },
        )

    def save_report_source(
        self,
        payload: dict[str, Any],
        *,
        file_name: str | None = None,
        file_content: bytes | None = None,
        file_mime_type: str = "",
        file_origin: str = "",
    ) -> dict[str, Any]:
        report_id = int(payload["report_id"]) if payload.get("report_id") else None
        return self._mutate_live_state(
            "postgres-save-report-source",
            lambda conn, upload_root: {
                "source": legacy_db.save_report_source(
                    conn,
                    upload_root,
                    report_id,
                    payload,
                    file_name=file_name,
                    file_content=file_content,
                    file_mime_type=file_mime_type,
                    file_origin=file_origin,
                )
            },
        )

    def delete_report_source(self, source_id: int) -> dict[str, Any]:
        return self._mutate_live_state(
            "postgres-delete-report-source",
            lambda conn, _upload_root: (legacy_db.delete_report_source(conn, source_id), {"ok": True})[1],
        )

    def process_next_background_job(self, worker_id: str, *, lease_seconds: int = legacy_db.DEFAULT_JOB_LEASE_SECONDS) -> bool:
        live_db_path = self.live_legacy_view()
        live_upload_root = self._prepare_live_storage_root()
        self._repoint_document_paths(live_db_path, live_upload_root)
        did_work = legacy_db.process_next_background_job(
            live_db_path,
            live_upload_root,
            worker_id,
            lease_seconds=lease_seconds,
        )
        if did_work:
            self.shadow.sync_from_sqlite_snapshot(live_db_path, live_upload_root, f"postgres-worker:{worker_id}")
        return did_work

    def create_company(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticker = str(payload.get("ticker", "")).strip().upper()
        if not ticker:
            raise ValueError("Ticker is required.")
        name = str(payload.get("name", "")).strip() or ticker
        timestamp = now_utc()
        session = self.shadow.session_factory()()
        try:
            company = Company(
                id=int((session.execute(select(func.coalesce(func.max(Company.id), 0))).scalar_one() or 0) + 1),
                workspace_id=1,
                public_id=f"company-{ticker.lower()}-{int(timestamp.timestamp())}",
                ticker=ticker,
                name=name,
                slug=slugify(ticker or name, f"company-{ticker.lower()}"),
                bucket="pool",
                current_stage_id=None,
                notes=str(payload.get("notes") or ""),
                created_by="",
                updated_by="",
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(company)
            session.commit()
            company_id = int(company.id)
        finally:
            session.close()
        return self.company_live(company_id)

    def update_company(self, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.shadow.session_factory()()
        try:
            company = session.get(Company, company_id)
            if company is None:
                raise KeyError("Company not found.")
            if "ticker" in payload:
                company.ticker = str(payload["ticker"]).upper().strip()
            if "name" in payload:
                company.name = str(payload["name"] or "").strip() or company.ticker
            if "bucket" in payload:
                company.bucket = str(payload["bucket"])
            if "current_stage_id" in payload:
                company.current_stage_id = payload["current_stage_id"]
            if "notes" in payload:
                company.notes = str(payload["notes"] or "")
            company.updated_at = now_utc()
            session.commit()
        finally:
            session.close()
        return self.company_live(company_id)

    def save_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_utc()
        stage_id = int(payload["stage_id"])
        markdown = str(payload.get("markdown") or "")
        schema = legacy_db.template_schema(markdown)
        session = self.shadow.session_factory()()
        try:
            stage_key = str(
                (
                    session.execute(select(Stage.key).where(Stage.id == stage_id)).scalar_one_or_none()
                )
                or ""
            )
            template_candidate = {
                "id": payload.get("id") or "pending",
                "stage_key": stage_key,
                "schema": schema,
            }
            assert_no_critical_issues(audit_template_record(template_candidate, strict=True), context="template payload")
            if payload.get("id"):
                existing = session.get(Template, int(payload["id"]))
                if existing is None:
                    raise KeyError("Template not found.")
                if int(existing.stage_id) != stage_id:
                    raise ValueError("Editing an existing template cannot change its stage. Create a new template instead.")
            next_version = int(
                (session.execute(select(func.coalesce(func.max(Template.version), 0)).where(Template.stage_id == stage_id)).scalar_one() or 0)
                + 1
            )
            active_templates = session.execute(
                select(Template).where(Template.stage_id == stage_id, Template.is_active.is_(True))
            ).scalars().all()
            for template in active_templates:
                template.is_active = False
                template.updated_at = timestamp
            template = Template(
                id=int((session.execute(select(func.coalesce(func.max(Template.id), 0))).scalar_one() or 0) + 1),
                workspace_id=1,
                public_id=f"template-{stage_id}-{next_version}-{int(timestamp.timestamp())}",
                stage_id=stage_id,
                name=str(payload.get("name", "Untitled Template")).strip(),
                version=next_version,
                description=str(payload.get("description") or ""),
                markdown=markdown,
                schema_json=schema,
                is_active=True,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(template)
            session.commit()
            template_id = int(template.id)
        finally:
            session.close()
        return self.template_live(template_id)

    def delete_template(self, template_id: int) -> dict[str, Any]:
        session = self.shadow.session_factory()()
        try:
            template = session.get(Template, template_id)
            if template is None:
                raise KeyError("Template not found.")
            timestamp = now_utc()
            references = int(
                session.execute(select(func.count()).select_from(Report).where(Report.template_id == template_id)).scalar_one() or 0
            )
            if references:
                template.is_active = False
                template.updated_at = timestamp
            else:
                session.delete(template)
            session.commit()
        finally:
            session.close()
        return {"ok": True}

    def save_monitoring_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        timestamp_dt = now_utc()
        timestamp = iso_utc(timestamp_dt)
        session = self.shadow.session_factory()()
        try:
            existing = session.get(MonitoringRule, int(payload["id"])) if payload.get("id") else None
            if payload.get("id") and existing is None:
                raise KeyError("Monitoring rule not found.")
            current_value = payload.get("current_value", existing.current_value if existing else None)
            threshold = payload.get("threshold_value", existing.threshold_value if existing else None)
            current_number = float(current_value) if current_value not in ("", None) else None
            threshold_number = float(threshold) if threshold not in ("", None) else None
            comparator = str(payload.get("comparator", existing.comparator if existing else "<=") or "<=")
            if comparator not in {"<", "<=", ">", ">=", "=", "=="}:
                raise ValueError("Invalid comparator.")
            metric_name = str(payload.get("metric_name", existing.metric_name if existing else "")).strip()
            unit = str(payload.get("unit", existing.unit if existing else "") or "")
            source = str(payload.get("source", existing.source if existing else "") or "")
            report_rule_key = str(payload.get("report_rule_key", existing.report_rule_key if existing else "") or "").strip()
            notes = str(payload.get("notes", existing.notes if existing else "") or "")
            if not report_rule_key and payload.get("report_id"):
                report_rule_key = legacy_db.objective_rule_key(metric_name, comparator, threshold_number, unit)
            if existing and existing.report_id:
                if (
                    metric_name != str(existing.metric_name)
                    or comparator != str(existing.comparator)
                    or threshold_number != existing.threshold_value
                    or unit != str(existing.unit or "")
                    or source != str(existing.source or "")
                    or report_rule_key != str(existing.report_rule_key or "")
                ):
                    raise ValueError("Report-owned monitoring rules can only update current_value and notes.")
                metric_name = str(existing.metric_name)
                comparator = str(existing.comparator)
                threshold_number = existing.threshold_value
                unit = str(existing.unit or "")
                source = str(existing.source or "")
                report_rule_key = str(existing.report_rule_key or "")
            triggered = 1 if legacy_db.evaluate_rule(comparator, current_number, threshold_number) else 0
            if existing:
                existing.report_rule_key = report_rule_key
                existing.metric_name = metric_name
                existing.comparator = comparator
                existing.threshold_value = threshold_number
                existing.unit = unit
                existing.current_value = current_number
                existing.source = source
                existing.triggered = bool(triggered)
                existing.notes = notes
                existing.last_checked_at = timestamp if current_number is not None else str(payload.get("last_checked_at", existing.last_checked_at or ""))
                existing.updated_at = timestamp_dt
                rule = existing
            else:
                rule = MonitoringRule(
                    id=int((session.execute(select(func.coalesce(func.max(MonitoringRule.id), 0))).scalar_one() or 0) + 1),
                    workspace_id=1,
                    company_id=int(payload["company_id"]),
                    report_id=payload.get("report_id"),
                    report_rule_key=report_rule_key,
                    metric_name=metric_name,
                    comparator=comparator,
                    threshold_value=threshold_number,
                    unit=unit,
                    current_value=current_number,
                    source=source,
                    triggered=bool(triggered),
                    notes=notes,
                    last_checked_at=timestamp if current_number is not None else "",
                    created_at=timestamp_dt,
                    updated_at=timestamp_dt,
                )
                session.add(rule)
            session.commit()
            result = {
                "id": int(rule.id),
                "company_id": int(rule.company_id),
                "report_id": int(rule.report_id) if rule.report_id is not None else None,
                "report_rule_key": rule.report_rule_key,
                "metric_name": rule.metric_name,
                "comparator": rule.comparator,
                "threshold_value": rule.threshold_value,
                "unit": rule.unit,
                "current_value": rule.current_value,
                "source": rule.source,
                "triggered": 1 if rule.triggered else 0,
                "notes": rule.notes,
                "last_checked_at": rule.last_checked_at,
                "created_at": iso_utc(rule.created_at),
                "updated_at": iso_utc(rule.updated_at),
            }
        finally:
            session.close()
        return {"rule": result}


def _delegate_native_method(name: str):
    def delegated(self: PostgresCompatibilityStore, *args: Any, **kwargs: Any):
        self.ensure_synced(force=False)
        return getattr(self._native, name)(*args, **kwargs)

    return delegated


for _delegated_name in (
    "bootstrap",
    "stages",
    "templates",
    "template",
    "companies",
    "company",
    "monitoring",
    "reports",
    "report",
    "create_company",
    "update_company",
    "save_template",
    "delete_template",
    "create_report",
    "preview_report",
    "update_report",
    "delete_report",
    "document_status",
    "document_record",
    "upload_documents",
    "save_report_source",
    "delete_report_source",
    "save_monitoring_rule",
    "process_next_background_job",
):
    setattr(PostgresCompatibilityStore, _delegated_name, _delegate_native_method(_delegated_name))
