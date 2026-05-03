from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from typing import Iterator

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text

from app.db.models import BackgroundJob
from app.db.models import Company
from app.db.models import Document
from app.db.models import MonitoringRule
from app.db.models import Report
from app.db.models import ReportSource
from app.db.models import Stage
from app.db.models import Template
from app.shadow import ShadowBackend
from app.shadow import now_utc
from app.shadow import slugify
from app.storage import StorageAdapter
from app.storage import storage_key_from_path

from funnel_app import db as legacy_db
from funnel_app.document_normalizer import normalize_document_file


def iso_utc(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed.isoformat(timespec="seconds")


def legacy_timestamp_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        if "T" in value:
            return value
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = parsed.astimezone(UTC)
        return parsed.isoformat(timespec="seconds")
    return iso_utc(value)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(slots=True)
class ReportRowContext:
    report: Report
    company: Company
    stage: Stage
    template: Template


class NativeAuthorityStore:
    native_authority = True

    def __init__(self, shadow: ShadowBackend):
        self.shadow = shadow

    @property
    def settings(self):
        return self.shadow.settings

    def ensure_synced(self, *, force: bool = False):
        return self.shadow.sync_from_source("native-authority", force=force)

    @contextmanager
    def session_scope(self) -> Iterator[Any]:
        session = self.shadow.session_factory()()
        try:
            yield session
        finally:
            session.close()

    def _storage(self) -> StorageAdapter:
        return StorageAdapter(self.settings)

    def _next_id(self, session: Any, model: Any) -> int:
        return int((session.execute(select(func.coalesce(func.max(model.id), 0))).scalar_one() or 0) + 1)

    def _stage_payload(self, stage: Stage) -> dict[str, Any]:
        return {
            "id": int(stage.id),
            "key": str(stage.key),
            "name": str(stage.name),
            "description": str(stage.description or ""),
            "sequence": int(stage.sequence),
            "is_active": 1 if stage.is_active else 0,
            "created_at": iso_utc(stage.created_at),
            "updated_at": iso_utc(stage.updated_at),
        }

    def _template_payload(self, template: Template, stage: Stage, *, include_markdown: bool = True) -> dict[str, Any]:
        item = {
            "id": int(template.id),
            "stage_id": int(template.stage_id),
            "name": str(template.name),
            "version": int(template.version),
            "description": str(template.description or ""),
            "markdown": str(template.markdown),
            "schema_json": json.dumps(template.schema_json or {}, ensure_ascii=False),
            "is_active": 1 if template.is_active else 0,
            "created_at": iso_utc(template.created_at),
            "updated_at": iso_utc(template.updated_at),
            "stage_name": str(stage.name),
            "stage_key": str(stage.key),
        }
        item["schema"] = legacy_db.stored_template_schema(item)
        item.pop("schema_json", None)
        if not include_markdown:
            item.pop("markdown", None)
        return item

    def _document_local_path(self, document: Document) -> Path:
        if str(document.legacy_storage_path or "").strip():
            return Path(str(document.legacy_storage_path))
        return self.settings.upload_root / str(document.storage_key)

    def _document_normalized_path(self, document: Document) -> Path:
        stored = str(document.normalized_text_path or "").strip()
        if stored:
            return Path(stored)
        fallback = self.settings.upload_root / str(document.company_id) / "normalized" / f"{int(document.id)}-{Path(str(document.stored_name)).stem}.txt"
        return fallback

    def _document_payload(self, document: Document) -> dict[str, Any]:
        item = {
            "id": int(document.id),
            "company_id": int(document.company_id),
            "report_id": int(document.report_id) if document.report_id is not None else None,
            "original_name": str(document.original_name),
            "stored_name": str(document.stored_name),
            "storage_path": str(self._document_local_path(document)),
            "mime_type": str(document.mime_type or ""),
            "size_bytes": int(document.size_bytes or 0),
            "notes": str(document.notes or ""),
            "normalized_text_path": str(self._document_normalized_path(document)),
            "normalized_status": str(document.normalized_status or ""),
            "normalized_format": str(document.normalized_format or ""),
            "normalized_method": str(document.normalized_method or ""),
            "normalized_notes": str(document.normalized_notes or ""),
            "normalized_preview": str(document.normalized_preview or ""),
            "normalized_updated_at": str(document.normalized_updated_at or ""),
            "uploaded_at": str(document.uploaded_at or ""),
        }
        return legacy_db.decorate_document_record(item)

    def _source_payload(
        self,
        source: ReportSource,
        *,
        report: Report,
        stage: Stage,
        document: Document | None = None,
        include_report_context: bool = False,
    ) -> dict[str, Any]:
        item = {
            "id": int(source.id),
            "report_id": int(source.report_id),
            "document_id": int(source.document_id) if source.document_id is not None else None,
            "title": str(source.title),
            "capture_kind": str(source.capture_kind or ""),
            "source_type": str(source.source_type or ""),
            "evidence_grade": str(source.evidence_grade or ""),
            "confidence": str(source.confidence or ""),
            "tags": list(source.tags_json or []),
            "url": str(source.url or ""),
            "canonical_url": str(source.canonical_url or ""),
            "link_only_reason": str(source.link_only_reason or ""),
            "snapshot_guidance_acknowledged": bool(source.snapshot_guidance_acknowledged),
            "capture_state": str(source.capture_state or ""),
            "capture_error": str(source.capture_error or ""),
            "citation": str(source.citation or ""),
            "notes": str(source.notes or ""),
            "created_at": iso_utc(source.created_at),
            "updated_at": iso_utc(source.updated_at),
        }
        if include_report_context:
            item["report_title"] = str(report.title)
            item["report_result"] = str(report.result or "")
            item["stage_name"] = str(stage.name)
            item["stage_key"] = str(stage.key)
            item["stage_sequence"] = int(stage.sequence)
        if document is not None:
            doc_payload = self._document_payload(document)
            item["document_name"] = str(document.original_name)
            item["document_mime_type"] = str(document.mime_type or "")
            item["normalized_status"] = doc_payload["normalized_status"]
            item["normalized_format"] = str(document.normalized_format or "")
            item["normalized_method"] = str(document.normalized_method or "")
            item["normalized_notes"] = str(document.normalized_notes or "")
            item["normalized_preview"] = str(document.normalized_preview or "")
            item["normalized_text_path"] = doc_payload["normalized_text_path"]
        else:
            item["document_name"] = None
            item["document_mime_type"] = None
            item["normalized_status"] = None
            item["normalized_format"] = None
            item["normalized_method"] = None
            item["normalized_notes"] = None
            item["normalized_preview"] = None
            item["normalized_text_path"] = None
        return legacy_db.decorate_source_record(item)

    def _monitoring_payload(self, rule: MonitoringRule, company: Company) -> dict[str, Any]:
        return {
            "id": int(rule.id),
            "company_id": int(rule.company_id),
            "report_id": int(rule.report_id) if rule.report_id is not None else None,
            "report_rule_key": str(rule.report_rule_key or ""),
            "metric_name": str(rule.metric_name or ""),
            "comparator": str(rule.comparator or ""),
            "threshold_value": rule.threshold_value,
            "unit": str(rule.unit or ""),
            "current_value": rule.current_value,
            "source": str(rule.source or ""),
            "triggered": 1 if rule.triggered else 0,
            "notes": str(rule.notes or ""),
            "last_checked_at": str(rule.last_checked_at or ""),
            "created_at": iso_utc(rule.created_at),
            "updated_at": iso_utc(rule.updated_at),
            "ticker": str(company.ticker),
            "company_name": str(company.name),
        }

    def _dashboard_monitoring_payload(self, rule: MonitoringRule, company: Company) -> dict[str, Any]:
        item = self._monitoring_payload(rule, company)
        item["name"] = item.pop("company_name")
        return item

    def _report_summary_payload(
        self,
        session: Any,
        report: Report,
        company: Company,
        stage: Stage,
        *,
        include_company: bool = False,
        include_completed_at: bool = False,
    ) -> dict[str, Any]:
        timestamps = session.execute(
            text("SELECT created_at, updated_at FROM reports WHERE id = :report_id"),
            {"report_id": int(report.id)},
        ).mappings().first()
        payload = {
            "id": int(report.id),
            "company_id": int(report.company_id),
            "title": str(report.title),
            "report_month": str(report.report_month or ""),
            "result": str(report.result or ""),
            "summary": str(report.summary or ""),
            "next_action": str(report.next_action or ""),
            "review_date": str(report.review_date or ""),
            "stage_id": int(report.stage_id),
            "stage_key": str(stage.key),
            "stage_name": str(stage.name),
            "stage_sequence": int(stage.sequence),
            "updated_at": legacy_timestamp_text(timestamps["updated_at"]) if timestamps and timestamps.get("updated_at") is not None else (iso_utc(report.updated_at) if report.updated_at is not None else None),
            "created_at": legacy_timestamp_text(timestamps["created_at"]) if timestamps and timestamps.get("created_at") is not None else (iso_utc(report.created_at) if report.created_at is not None else None),
        }
        if include_company:
            payload["ticker"] = str(company.ticker)
            payload["company_name"] = str(company.name)
        if include_completed_at:
            payload["completed_at"] = str(report.completed_at or "")
        return payload

    def _company_latest_report(self, session: Any, company_id: int) -> ReportRowContext | None:
        rows = (
            session.execute(
                select(Report, Stage, Template, Company)
                .join(Stage, Stage.id == Report.stage_id)
                .join(Template, Template.id == Report.template_id)
                .join(Company, Company.id == Report.company_id)
                .where(Report.company_id == company_id, Report.result != "Draft")
                .order_by(Report.updated_at.desc(), Report.id.desc())
            )
            .all()
        )
        if not rows:
            return None
        report, stage, template, company = rows[0]
        return ReportRowContext(report=report, company=company, stage=stage, template=template)

    def _company_payload(self, session: Any, company: Company, *, detail: bool = False) -> dict[str, Any]:
        stage = session.get(Stage, company.current_stage_id) if company.current_stage_id is not None else None
        payload: dict[str, Any] = {
            "id": int(company.id),
            "ticker": str(company.ticker),
            "name": str(company.name),
            "bucket": str(company.bucket),
            "current_stage_id": int(company.current_stage_id) if company.current_stage_id is not None else None,
            "notes": str(company.notes or ""),
            "created_at": iso_utc(company.created_at),
            "updated_at": iso_utc(company.updated_at),
            "current_stage_name": str(stage.name) if stage is not None else None,
            "current_stage_key": str(stage.key) if stage is not None else None,
            "latest_result": None,
            "latest_summary": None,
            "review_date": None,
            "next_action": None,
            "watchlist_conditions": None,
            "archive_red_flags": None,
        }
        latest = self._company_latest_report(session, int(company.id))
        if latest is not None:
            payload["latest_result"] = str(latest.report.result or "")
            payload["latest_summary"] = str(latest.report.summary or "")
            payload["review_date"] = str(latest.report.review_date or "")
            payload["next_action"] = str(latest.report.next_action or "")
            payload["watchlist_conditions"] = str(latest.report.watchlist_conditions or "")
            payload["archive_red_flags"] = str(latest.report.archive_red_flags or "")
            if not payload["latest_summary"] or not payload["watchlist_conditions"] or not payload["archive_red_flags"] or not payload["next_action"] or not payload["review_date"]:
                derived = legacy_db.derive_report_summary(
                    self._template_payload(latest.template, latest.stage),
                    latest.report.responses_json or {},
                    latest.report.metrics_json or {},
                )
                for key in ("latest_summary", "watchlist_conditions", "archive_red_flags", "next_action", "review_date"):
                    if not payload.get(key) and derived.get(key):
                        payload[key] = derived[key]
        if detail:
            payload["reports"] = self._report_summaries_for_company(session, int(company.id))
            payload["documents"] = self._documents_for_company(session, int(company.id))
            payload["company_sources"] = self._company_sources_for_company(session, int(company.id))
            payload["monitoring_rules"] = self._monitoring_rules(session, company_id=int(company.id))
        return payload

    def _report_context_row(self, session: Any, report_id: int) -> ReportRowContext:
        row = (
            session.execute(
                select(Report, Company, Stage, Template)
                .join(Company, Company.id == Report.company_id)
                .join(Stage, Stage.id == Report.stage_id)
                .join(Template, Template.id == Report.template_id)
                .where(Report.id == report_id)
            )
            .first()
        )
        if row is None:
            raise KeyError("Report not found.")
        report, company, stage, template = row
        return ReportRowContext(report=report, company=company, stage=stage, template=template)

    def _lightweight_report_payload(self, session: Any, report_id: int) -> dict[str, Any]:
        ctx = self._report_context_row(session, report_id)
        template = self._template_payload(ctx.template, ctx.stage)
        return {
            "id": int(ctx.report.id),
            "company_id": int(ctx.report.company_id),
            "stage_id": int(ctx.report.stage_id),
            "template_id": int(ctx.report.template_id),
            "title": str(ctx.report.title),
            "report_month": str(ctx.report.report_month or ""),
            "result": str(ctx.report.result or ""),
            "summary": str(ctx.report.summary or ""),
            "next_action": str(ctx.report.next_action or ""),
            "review_date": str(ctx.report.review_date or ""),
            "updated_at": iso_utc(ctx.report.updated_at),
            "created_at": iso_utc(ctx.report.created_at),
            "responses": dict(ctx.report.responses_json or {}),
            "metrics": dict(ctx.report.metrics_json or {}),
            "ticker": str(ctx.company.ticker),
            "company_name": str(ctx.company.name),
            "stage_name": str(ctx.stage.name),
            "stage_key": str(ctx.stage.key),
            "stage_sequence": int(ctx.stage.sequence),
            "template": template,
        }

    @contextmanager
    def _patched_latest_completed_report(self, session: Any) -> Iterator[None]:
        original = legacy_db.latest_completed_report_for_stage

        def replacement(_conn: Any, company_id: int, stage_key: str) -> dict[str, Any] | None:
            rows = (
                session.execute(
                    select(Report.id)
                    .join(Stage, Stage.id == Report.stage_id)
                    .where(Report.company_id == int(company_id), Stage.key == str(stage_key), Report.result != "Draft")
                    .order_by(Report.updated_at.desc(), Report.id.desc())
                    .limit(1)
                )
                .scalars()
                .all()
            )
            if not rows:
                return None
            return self._lightweight_report_payload(session, int(rows[0]))

        legacy_db.latest_completed_report_for_stage = replacement
        try:
            yield
        finally:
            legacy_db.latest_completed_report_for_stage = original

    def _workflow_context(self, session: Any, report: dict[str, Any]) -> dict[str, Any]:
        current_stage = session.get(Stage, int(report["stage_id"]))
        next_stage = (
            session.execute(
                select(Stage)
                .where(Stage.is_active.is_(True), Stage.sequence > int(current_stage.sequence))
                .order_by(Stage.sequence, Stage.id)
                .limit(1)
            )
            .scalars()
            .first()
            if current_stage is not None
            else None
        )
        previous_rows = (
            session.execute(
                select(Report, Stage)
                .join(Stage, Stage.id == Report.stage_id)
                .where(
                    Report.company_id == int(report["company_id"]),
                    Report.result != "Draft",
                    Stage.sequence < int(current_stage.sequence if current_stage is not None else 0),
                )
                .order_by(Stage.sequence, Report.updated_at.desc(), Report.id.desc())
            )
            .all()
        )
        previous_reports: list[dict[str, Any]] = []
        latest_stage_keys: set[str] = set()
        for previous_report, stage in previous_rows:
            item = {
                "id": int(previous_report.id),
                "stage_id": int(previous_report.stage_id),
                "template_id": int(previous_report.template_id),
                "title": str(previous_report.title),
                "report_month": str(previous_report.report_month or ""),
                "result": str(previous_report.result or ""),
                "summary": str(previous_report.summary or ""),
                "next_action": str(previous_report.next_action or ""),
                "review_date": str(previous_report.review_date or ""),
                "updated_at": iso_utc(previous_report.updated_at) if previous_report.updated_at is not None else None,
                "stage_name": str(stage.name),
                "stage_key": str(stage.key),
                "stage_sequence": int(stage.sequence),
            }
            item["is_latest_for_stage"] = str(stage.key) not in latest_stage_keys
            if item["is_latest_for_stage"]:
                latest_stage_keys.add(str(stage.key))
            item["resource_uri"] = f"funnel://reports/{int(previous_report.id)}"
            item["api_url"] = f"/api/reports/{int(previous_report.id)}"
            previous_reports.append(item)
        workflow = {
            "current_stage": {
                "id": int(current_stage.id) if current_stage is not None else int(report["stage_id"]),
                "key": str(current_stage.key) if current_stage is not None else str(report.get("stage_key") or ""),
                "name": str(current_stage.name) if current_stage is not None else str(report.get("stage_name") or ""),
                "sequence": int(current_stage.sequence) if current_stage is not None else int(report.get("stage_sequence") or 0),
            },
            "next_stage": (
                {
                    "id": int(next_stage.id),
                    "key": str(next_stage.key),
                    "name": str(next_stage.name),
                    "sequence": int(next_stage.sequence),
                }
                if next_stage is not None
                else None
            ),
            "previous_reports": previous_reports,
        }
        workflow["latest_previous_reports"] = [item for item in previous_reports if item.get("is_latest_for_stage")]
        workflow["latest_upstream_report"] = legacy_db.latest_upstream_report(workflow)
        return workflow

    def _cited_source_ids_for_report(self, session: Any, report_id: int) -> set[str]:
        model = session.get(Report, int(report_id))
        if model is None:
            return set()
        return legacy_db.linked_source_ids(model.field_sources_json or {})

    def _company_sources_for_company(self, session: Any, company_id: int) -> list[dict[str, Any]]:
        rows = (
            session.execute(
                select(ReportSource, Report, Stage, Document)
                .join(Report, Report.id == ReportSource.report_id)
                .join(Stage, Stage.id == Report.stage_id)
                .outerjoin(Document, Document.id == ReportSource.document_id)
                .where(Report.company_id == company_id)
                .order_by(Report.updated_at.desc(), ReportSource.updated_at.desc(), ReportSource.id.desc())
            )
            .all()
        )
        return [
            self._source_payload(source, report=report, stage=stage, document=document, include_report_context=True)
            for source, report, stage, document in rows
        ]

    def _report_sources(self, session: Any, report_id: int) -> list[dict[str, Any]]:
        ctx = self._report_context_row(session, report_id)
        rows = (
            session.execute(
                select(ReportSource, Document)
                .outerjoin(Document, Document.id == ReportSource.document_id)
                .where(ReportSource.report_id == report_id)
                .order_by(ReportSource.updated_at.desc(), ReportSource.id.desc())
            )
            .all()
        )
        return [self._source_payload(source, report=ctx.report, stage=ctx.stage, document=document, include_report_context=False) for source, document in rows]

    def _documents_for_company(self, session: Any, company_id: int, *, report_id: int | None = None) -> list[dict[str, Any]]:
        stmt = select(Document).where(Document.company_id == company_id)
        if report_id is not None:
            stmt = stmt.where(Document.report_id == report_id)
        rows = session.execute(stmt.order_by(Document.uploaded_at.desc(), Document.id.desc())).scalars().all()
        return [self._document_payload(row) for row in rows]

    def _monitoring_rules(self, session: Any, *, company_id: int | None = None, bucket: str | None = None) -> list[dict[str, Any]]:
        stmt = select(MonitoringRule, Company).join(Company, Company.id == MonitoringRule.company_id)
        if company_id is not None:
            stmt = stmt.where(MonitoringRule.company_id == company_id)
        if bucket:
            stmt = stmt.where(Company.bucket == bucket)
        rows = session.execute(stmt.order_by(MonitoringRule.triggered.desc(), MonitoringRule.updated_at.desc())).all()
        return [self._monitoring_payload(rule, company) for rule, company in rows]

    def _report_summaries_for_company(self, session: Any, company_id: int) -> list[dict[str, Any]]:
        rows = (
            session.execute(
                select(Report, Company, Stage)
                .join(Company, Company.id == Report.company_id)
                .join(Stage, Stage.id == Report.stage_id)
                .where(Report.company_id == company_id)
                .order_by(Report.updated_at.desc(), Report.id.desc())
            )
            .all()
        )
        return [
            self._report_summary_payload(session, report, company, stage, include_company=False, include_completed_at=False)
            for report, company, stage in rows
        ]

    def _enriched_report_objective_rules(self, session: Any, report: dict[str, Any]) -> list[dict[str, Any]]:
        stored_rules = legacy_db.normalize_objective_rules(report.get("watchlist_objective_rules") or [])
        runtime_rows = (
            session.execute(select(MonitoringRule).where(MonitoringRule.report_id == int(report["id"])).order_by(MonitoringRule.id))
            .scalars()
            .all()
        )
        runtime_by_rule_key = {
            legacy_db.monitoring_rule_report_key(
                {
                    "report_rule_key": str(rule.report_rule_key or ""),
                    "metric_name": str(rule.metric_name or ""),
                    "comparator": str(rule.comparator or ""),
                    "threshold_value": rule.threshold_value,
                    "unit": str(rule.unit or ""),
                }
            ): rule
            for rule in runtime_rows
        }
        rules: list[dict[str, Any]] = []
        for rule in stored_rules:
            runtime = runtime_by_rule_key.get(rule["rule_key"])
            rules.append(
                {
                    **rule,
                    "current_value": runtime.current_value if runtime is not None else rule.get("current_value"),
                    "notes": str(runtime.notes or "") if runtime is not None else str(rule.get("notes", "")),
                }
            )
        return rules

    def _suggested_company_sources(self, session: Any, report: dict[str, Any]) -> list[dict[str, Any]]:
        company_sources = list(report.get("company_sources") or [])
        if not company_sources:
            return []
        current_ids = {str(source["id"]) for source in (report.get("sources") or [])}
        upstream = legacy_db.latest_upstream_report(report.get("workflow") or {})
        upstream_report_id = int(upstream["id"]) if upstream else 0
        cited_ids = self._cited_source_ids_for_report(session, upstream_report_id) if upstream_report_id else set()
        upstream_source_ids = {
            str(source["id"])
            for source in company_sources
            if upstream_report_id and int(source.get("report_id") or 0) == upstream_report_id
        }
        suggested: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for source in company_sources:
            source_id = str(source["id"])
            if source_id in current_ids:
                continue
            if source_id in cited_ids:
                bucket = 0
                reason = "cited_in_latest_upstream_report"
            elif source_id in upstream_source_ids:
                bucket = 1
                reason = "uploaded_in_latest_upstream_report"
            else:
                bucket = 2
                reason = "from_company_library"
            suggested_source = dict(source)
            suggested_source["suggestion_reason"] = reason
            suggested.append((legacy_db.suggested_source_sort_key(suggested_source, priority_bucket=bucket), suggested_source))
        suggested.sort(key=lambda item: item[0])
        return [source for _, source in suggested]

    def _report_payload(self, session: Any, report_id: int) -> dict[str, Any]:
        ctx = self._report_context_row(session, report_id)
        report = {
            "id": int(ctx.report.id),
            "company_id": int(ctx.report.company_id),
            "stage_id": int(ctx.report.stage_id),
            "template_id": int(ctx.report.template_id),
            "title": str(ctx.report.title),
            "report_month": str(ctx.report.report_month or ""),
            "revision": int(ctx.report.revision),
            "responses": dict(ctx.report.responses_json or {}),
            "metrics": dict(ctx.report.metrics_json or {}),
            "section_ratings": dict(ctx.report.section_ratings_json or {}),
            "data_quality": dict(ctx.report.data_quality_json or {}),
            "field_sources": dict(ctx.report.field_sources_json or {}),
            "field_notes": dict(ctx.report.field_notes_json or {}),
            "field_exceptions": dict(ctx.report.field_exceptions_json or {}),
            "result": str(ctx.report.result or ""),
            "summary": str(ctx.report.summary or ""),
            "watchlist_conditions": str(ctx.report.watchlist_conditions or ""),
            "watchlist_objective_rules": list(ctx.report.watchlist_objective_rules_json or []),
            "watchlist_subjective_rules": str(ctx.report.watchlist_subjective_rules or ""),
            "archive_red_flags": str(ctx.report.archive_red_flags or ""),
            "next_action": str(ctx.report.next_action or ""),
            "review_date": str(ctx.report.review_date or ""),
            "completed_at": str(ctx.report.completed_at or ""),
            "created_at": iso_utc(ctx.report.created_at),
            "updated_at": iso_utc(ctx.report.updated_at),
            "ticker": str(ctx.company.ticker),
            "company_name": str(ctx.company.name),
            "stage_name": str(ctx.stage.name),
            "stage_key": str(ctx.stage.key),
            "stage_sequence": int(ctx.stage.sequence),
            "template_name": str(ctx.template.name),
            "resource_uri": f"funnel://reports/{int(ctx.report.id)}",
            "api_url": f"/api/reports/{int(ctx.report.id)}",
        }
        report["template"] = self._template_payload(ctx.template, ctx.stage)
        report["documents"] = self._documents_for_company(session, int(ctx.company.id), report_id=int(ctx.report.id))
        report["sources"] = self._report_sources(session, int(ctx.report.id))
        report["company_sources"] = self._company_sources_for_company(session, int(ctx.company.id))
        report["workflow"] = self._workflow_context(session, report)
        report["suggested_sources"] = self._suggested_company_sources(session, report)
        report["watchlist_objective_rules"] = self._enriched_report_objective_rules(session, report)
        report.update(legacy_db.normalize_report_state(report))
        with self._patched_latest_completed_report(session):
            (
                auto_inherited_responses,
                inherited_screening,
                inherited_business_underwriting,
                inherited_management_underwriting,
                inherited_financial_underwriting,
                inherited_valuation_position_size,
            ) = legacy_db.auto_inherited_state(None, report)
        report["auto_inherited_fields"] = sorted(auto_inherited_responses)
        report["inherited_screening"] = inherited_screening
        report["inherited_business_underwriting"] = inherited_business_underwriting
        report["inherited_management_underwriting"] = inherited_management_underwriting
        report["inherited_financial_underwriting"] = inherited_financial_underwriting
        report["inherited_valuation_position_size"] = inherited_valuation_position_size
        for field_id, value in auto_inherited_responses.items():
            report["responses"][field_id] = value
        agent_contract = legacy_db.build_agent_contract(report)
        if agent_contract:
            report["agent_contract"] = agent_contract
            report["completion"] = agent_contract.get("completion", {})
        return report

    def _sort_companies(self, companies: list[dict[str, Any]], order: str | None) -> list[dict[str, Any]]:
        key = str(order or "updated_desc")
        if key == "ticker_asc":
            return sorted(companies, key=lambda item: (str(item.get("ticker") or ""), str(item.get("name") or "")))
        if key == "ticker_desc":
            return sorted(companies, key=lambda item: (str(item.get("ticker") or ""), str(item.get("name") or "")), reverse=True)
        if key == "name_asc":
            return sorted(companies, key=lambda item: (str(item.get("name") or ""), str(item.get("ticker") or "")))
        if key == "name_desc":
            return sorted(companies, key=lambda item: (str(item.get("name") or ""), str(item.get("ticker") or "")), reverse=True)
        if key == "review_date_asc":
            return sorted(companies, key=lambda item: (0 if str(item.get("review_date") or "") else 1, str(item.get("review_date") or ""), str(item.get("ticker") or "")))
        if key == "review_date_desc":
            return sorted(
                companies,
                key=lambda item: (
                    0 if str(item.get("review_date") or "") else 1,
                    tuple(-ord(ch) for ch in str(item.get("review_date") or "")),
                    str(item.get("ticker") or ""),
                ),
            )
        if key == "status_asc":
            return sorted(
                companies,
                key=lambda item: (
                    str(item.get("bucket") or ""),
                    int(item.get("current_stage_id") or 999),
                    str(item.get("ticker") or ""),
                ),
            )
        if key == "updated_asc":
            return sorted(companies, key=lambda item: (str(item.get("updated_at") or ""), str(item.get("ticker") or "")))
        return sorted(
            companies,
            key=lambda item: (
                tuple(-ord(ch) for ch in str(item.get("updated_at") or "")),
                str(item.get("ticker") or ""),
            ),
        )

    def _sort_reports(self, reports: list[dict[str, Any]], order: str | None) -> list[dict[str, Any]]:
        key = str(order or "updated_desc")
        if key == "completed_desc":
            return sorted(
                reports,
                key=lambda item: (
                    0 if str(item.get("completed_at") or "") else 1,
                    tuple(-ord(ch) for ch in str(item.get("completed_at") or "")),
                    -int(item.get("id") or 0),
                ),
            )
        if key == "completed_asc":
            return sorted(reports, key=lambda item: (0 if str(item.get("completed_at") or "") else 1, str(item.get("completed_at") or ""), int(item.get("id") or 0)))
        if key == "updated_asc":
            return sorted(reports, key=lambda item: (str(item.get("updated_at") or ""), int(item.get("id") or 0)))
        if key == "company_asc":
            return sorted(reports, key=lambda item: (str(item.get("ticker") or ""), str(item.get("company_name") or ""), -int(item.get("id") or 0)))
        if key == "company_desc":
            return sorted(
                reports,
                key=lambda item: (
                    tuple(-ord(ch) for ch in str(item.get("ticker") or "")),
                    tuple(-ord(ch) for ch in str(item.get("company_name") or "")),
                    -int(item.get("id") or 0),
                ),
            )
        if key == "stage_asc":
            return sorted(
                reports,
                key=lambda item: (
                    int(item.get("stage_sequence") or 0),
                    tuple(-ord(ch) for ch in str(item.get("completed_at") or "")),
                    -int(item.get("id") or 0),
                ),
            )
        if key == "stage_desc":
            return sorted(
                reports,
                key=lambda item: (
                    -int(item.get("stage_sequence") or 0),
                    tuple(-ord(ch) for ch in str(item.get("completed_at") or "")),
                    -int(item.get("id") or 0),
                ),
            )
        if key == "result_asc":
            return sorted(
                reports,
                key=lambda item: (
                    str(item.get("result") or ""),
                    tuple(-ord(ch) for ch in str(item.get("completed_at") or "")),
                    -int(item.get("id") or 0),
                ),
            )
        if key == "result_desc":
            return sorted(
                reports,
                key=lambda item: (
                    tuple(-ord(ch) for ch in str(item.get("result") or "")),
                    tuple(-ord(ch) for ch in str(item.get("completed_at") or "")),
                    -int(item.get("id") or 0),
                ),
            )
        if key == "title_asc":
            return sorted(reports, key=lambda item: (str(item.get("title") or ""), -int(item.get("id") or 0)))
        if key == "title_desc":
            return sorted(
                reports,
                key=lambda item: (tuple(-ord(ch) for ch in str(item.get("title") or "")), -int(item.get("id") or 0)),
            )
        return sorted(
            reports,
            key=lambda item: (
                tuple(-ord(ch) for ch in str(item.get("updated_at") or "")),
                -int(item.get("id") or 0),
            ),
        )

    def _apply_report_result(self, session: Any, report: Report, result: str) -> None:
        company = session.get(Company, int(report.company_id))
        stage = session.get(Stage, int(report.stage_id))
        if company is None or stage is None:
            return
        if result == legacy_db.RESULT_PROCEED:
            next_stage = (
                session.execute(
                    select(Stage)
                    .where(Stage.is_active.is_(True), Stage.sequence > int(stage.sequence))
                    .order_by(Stage.sequence, Stage.id)
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if next_stage is not None:
                company.bucket = "funnel"
                company.current_stage_id = int(next_stage.id)
            else:
                company.bucket = "monitoring"
                company.current_stage_id = None
        elif result == legacy_db.RESULT_WATCHLIST:
            company.bucket = "watchlist"
            company.current_stage_id = None
        elif result == legacy_db.RESULT_ARCHIVE:
            company.bucket = "archive"
            company.current_stage_id = None
        else:
            stage_key = legacy_db.return_stage_key_from_result(result)
            if stage_key:
                target = session.execute(select(Stage).where(Stage.key == stage_key).limit(1)).scalars().first()
                company.bucket = "funnel"
                company.current_stage_id = int(target.id) if target is not None else int(report.stage_id)
        company.updated_at = now_utc()

    def _reconcile_company_position(self, session: Any, company_id: int) -> None:
        company = session.get(Company, company_id)
        if company is None:
            return
        latest_completed = (
            session.execute(
                select(Report)
                .where(Report.company_id == company_id, Report.result != "Draft")
                .order_by(Report.updated_at.desc(), Report.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if latest_completed is not None:
            self._apply_report_result(session, latest_completed, str(latest_completed.result or ""))
            return
        latest_draft = (
            session.execute(
                select(Report)
                .where(Report.company_id == company_id)
                .order_by(Report.updated_at.desc(), Report.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        company.bucket = "funnel" if latest_draft is not None else "pool"
        company.current_stage_id = int(latest_draft.stage_id) if latest_draft is not None else None
        company.updated_at = now_utc()

    def _sync_report_monitoring_rules(self, session: Any, report_id: int, company_id: int, result: str, desired_rules: list[dict[str, Any]] | None) -> None:
        normalized_rules = legacy_db.normalize_objective_rules(desired_rules or [])
        if result != legacy_db.RESULT_WATCHLIST:
            normalized_rules = []
        existing = session.execute(select(MonitoringRule).where(MonitoringRule.report_id == report_id).order_by(MonitoringRule.id)).scalars().all()
        existing_by_rule_key = {
            legacy_db.monitoring_rule_report_key(
                {
                    "report_rule_key": str(rule.report_rule_key or ""),
                    "metric_name": str(rule.metric_name or ""),
                    "comparator": str(rule.comparator or ""),
                    "threshold_value": rule.threshold_value,
                    "unit": str(rule.unit or ""),
                }
            ): rule
            for rule in existing
        }
        desired_keys = {rule["rule_key"] for rule in normalized_rules}
        for rule in existing:
            rule_key = legacy_db.monitoring_rule_report_key(
                {
                    "report_rule_key": str(rule.report_rule_key or ""),
                    "metric_name": str(rule.metric_name or ""),
                    "comparator": str(rule.comparator or ""),
                    "threshold_value": rule.threshold_value,
                    "unit": str(rule.unit or ""),
                }
            )
            if rule_key not in desired_keys:
                session.delete(rule)
        timestamp_dt = now_utc()
        timestamp = iso_utc(timestamp_dt)
        for entry in normalized_rules:
            existing_rule = existing_by_rule_key.get(entry["rule_key"])
            current_number = existing_rule.current_value if existing_rule is not None else entry.get("current_value")
            threshold_number = entry["threshold_value"]
            comparator = entry["comparator"]
            triggered = legacy_db.evaluate_rule(comparator, current_number, threshold_number)
            if existing_rule is not None:
                existing_rule.report_rule_key = entry["rule_key"]
                existing_rule.metric_name = entry["metric_name"]
                existing_rule.comparator = comparator
                existing_rule.threshold_value = threshold_number
                existing_rule.unit = entry.get("unit", "")
                existing_rule.current_value = current_number
                existing_rule.source = entry.get("source", "") or "Report objective rule"
                existing_rule.triggered = bool(triggered)
                if not str(existing_rule.notes or "").strip():
                    existing_rule.notes = str(entry.get("notes", "") or "")
                existing_rule.last_checked_at = timestamp if current_number is not None else ""
                existing_rule.updated_at = timestamp_dt
                continue
            session.add(
                MonitoringRule(
                    id=self._next_id(session, MonitoringRule),
                    workspace_id=1,
                    company_id=company_id,
                    report_id=report_id,
                    report_rule_key=entry["rule_key"],
                    metric_name=entry["metric_name"],
                    comparator=comparator,
                    threshold_value=threshold_number,
                    unit=entry.get("unit", ""),
                    current_value=current_number,
                    source=entry.get("source", "") or "Report objective rule",
                    triggered=bool(triggered),
                    notes=str(entry.get("notes", "") or ""),
                    last_checked_at=timestamp if current_number is not None else "",
                    created_at=timestamp_dt,
                    updated_at=timestamp_dt,
                )
            )

    def _report_update_context(self, report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        finalize_provided = "finalize" in payload
        finalize = legacy_db.parse_boolean_flag(payload.pop("finalize", False), field_name="finalize") if finalize_provided else False
        expected_revision_raw = payload.pop("expected_revision", report.get("revision"))
        try:
            expected_revision = int(expected_revision_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("expected_revision must be an integer.") from exc
        current_revision = int(report.get("revision") or 1)
        if expected_revision != current_revision:
            raise legacy_db.ReportRevisionConflict(int(report["id"]), current_revision, str(report.get("updated_at") or ""))
        merged_payload = legacy_db.synchronized_report_payload(report, payload)
        merged_payload = legacy_db.merged_report_update_payload(report, merged_payload)
        desired_objective_rules = None
        if "watchlist_objective_rules" in merged_payload:
            desired_objective_rules = legacy_db.normalize_objective_rules(merged_payload["watchlist_objective_rules"])
        legacy_db.validate_report_update_payload(report, merged_payload)
        requested_result = str(merged_payload.get("result") or report.get("result") or "Draft")
        if not finalize_provided and requested_result in legacy_db.REPORT_ACTIONS and requested_result != str(report.get("result") or "Draft"):
            finalize = True
        enforce_completion_gate = finalize_provided and finalize
        persisted_result = requested_result if finalize else str(report.get("result") or "Draft")
        if not finalize and persisted_result not in {"Draft", *legacy_db.REPORT_ACTIONS}:
            persisted_result = "Draft"
        if enforce_completion_gate and requested_result not in legacy_db.REPORT_ACTIONS:
            raise ValueError("Choose a final decision before finalizing.")
        completion_payload = dict(merged_payload)
        if desired_objective_rules is not None:
            completion_payload["watchlist_objective_rules"] = desired_objective_rules
        completion_candidate = legacy_db.report_state_with_payload(
            report,
            completion_payload,
            persisted_result=persisted_result if not finalize else requested_result,
        )
        completion = legacy_db.exhaustive_report_completion(completion_candidate)
        return {
            "report": report,
            "payload": merged_payload,
            "completion_payload": completion_payload,
            "desired_objective_rules": desired_objective_rules,
            "requested_result": requested_result,
            "persisted_result": persisted_result,
            "finalize": finalize,
            "enforce_completion_gate": enforce_completion_gate,
            "expected_revision": expected_revision,
            "completion_candidate": completion_candidate,
            "completion": completion,
        }

    def _create_document_record(
        self,
        session: Any,
        *,
        company_id: int,
        original_name: str,
        content: bytes,
        report_id: int | None,
        notes: str,
        mime_type: str,
    ) -> Document:
        safe_name = legacy_db.sanitize_filename(original_name)
        # Legacy consumes one UUID while entering the surrounding savepoint
        # before generating the stored filename. Mirror that sequence.
        legacy_db.uuid.uuid4()
        stored_name = f"{legacy_db.datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{legacy_db.uuid.uuid4().hex[:10]}-{safe_name}"
        company_dir = self.settings.upload_root / str(company_id)
        company_dir.mkdir(parents=True, exist_ok=True)
        storage_path = company_dir / stored_name
        storage_path.write_bytes(content)
        timestamp_dt = now_utc()
        uploaded_at = iso_utc(timestamp_dt)
        normalized_dir = company_dir / "normalized"
        normalized_path = normalized_dir / f"{self._next_id(session, Document)}-{Path(safe_name).stem}.txt"
        storage_key = storage_key_from_path(self.settings.upload_root, storage_path, str(storage_path.name))
        normalized_storage_key = storage_key_from_path(self.settings.upload_root, normalized_path, str(normalized_path.name))
        normalized_updated_at = iso_utc(now_utc())
        document = Document(
            id=self._next_id(session, Document),
            workspace_id=1,
            public_id=f"document-{company_id}-{int(timestamp_dt.timestamp())}-{stored_name[:12]}",
            company_id=company_id,
            report_id=report_id,
            original_name=original_name,
            stored_name=stored_name,
            storage_key=storage_key,
            legacy_storage_path=str(storage_path),
            mime_type=mime_type or "",
            size_bytes=len(content),
            content_sha256=sha256_bytes(content),
            notes=notes,
            normalized_storage_key=normalized_storage_key,
            normalized_text_path=str(normalized_path),
            normalized_status=legacy_db.DOCUMENT_STATUS_PENDING,
            normalized_format="",
            normalized_method="",
            normalized_notes="",
            normalized_preview="",
            normalized_updated_at=normalized_updated_at,
            uploaded_at=uploaded_at,
        )
        session.add(document)
        session.flush()
        session.add(
            BackgroundJob(
                id=self._next_id(session, BackgroundJob),
                workspace_id=1,
                kind=legacy_db.JOB_KIND_DOCUMENT_NORMALIZATION,
                document_id=int(document.id),
                payload_json={"document_id": int(document.id)},
                status=legacy_db.JOB_STATUS_PENDING,
                attempt_count=0,
                max_attempts=legacy_db.MAX_JOB_ATTEMPTS,
                leased_by="",
                leased_at="",
                available_at=uploaded_at,
                last_error="",
                completed_at="",
                created_at=timestamp_dt,
                updated_at=timestamp_dt,
            )
        )
        return document

    def _sync_report_source_capture_for_document(self, session: Any, document_id: int) -> None:
        document = session.get(Document, document_id)
        if document is None:
            return
        doc_payload = self._document_payload(document)
        capture_state, capture_error = legacy_db.source_capture_state_for_document(doc_payload)
        sources = session.execute(select(ReportSource).where(ReportSource.document_id == document_id)).scalars().all()
        for source in sources:
            source.capture_state = capture_state
            source.capture_error = capture_error
            if not source.updated_at:
                source.updated_at = now_utc()

    def _lease_background_job(self, session: Any, worker_id: str, *, lease_seconds: int) -> BackgroundJob | None:
        now_dt = now_utc()
        now_iso_value = iso_utc(now_dt)
        stale_cutoff = now_dt - timedelta(seconds=lease_seconds)
        jobs = session.execute(select(BackgroundJob).order_by(BackgroundJob.id)).scalars().all()
        candidate: BackgroundJob | None = None
        for job in jobs:
            if job.status == legacy_db.JOB_STATUS_PENDING and (not str(job.available_at or "") or str(job.available_at) <= now_iso_value):
                candidate = job
                break
        if candidate is None:
            for job in jobs:
                if job.status != legacy_db.JOB_STATUS_RUNNING or not str(job.leased_at or ""):
                    continue
                try:
                    leased_at = datetime.fromisoformat(str(job.leased_at))
                except ValueError:
                    leased_at = stale_cutoff
                if leased_at <= stale_cutoff:
                    candidate = job
                    break
        if candidate is None:
            return None
        candidate.status = legacy_db.JOB_STATUS_RUNNING
        candidate.attempt_count = int(candidate.attempt_count or 0) + 1
        candidate.leased_by = worker_id
        candidate.leased_at = now_iso_value
        candidate.updated_at = now_dt
        session.flush()
        return candidate

    def _fail_job(self, session: Any, job: BackgroundJob, *, message: str, update_document_failure: bool = False) -> None:
        now_dt = now_utc()
        now_iso_value = iso_utc(now_dt)
        if int(job.attempt_count or 0) >= int(job.max_attempts or legacy_db.MAX_JOB_ATTEMPTS):
            job.status = legacy_db.JOB_STATUS_FAILED
            job.leased_by = ""
            job.leased_at = ""
            job.last_error = message
            job.completed_at = now_iso_value
            job.updated_at = now_dt
        else:
            backoff_seconds = min(30, 2 ** max(0, int(job.attempt_count or 1) - 1))
            retry_at = (now_dt + timedelta(seconds=backoff_seconds)).replace(microsecond=0).isoformat()
            job.status = legacy_db.JOB_STATUS_PENDING
            job.leased_by = ""
            job.leased_at = ""
            job.available_at = retry_at
            job.last_error = message
            job.updated_at = now_dt
        if update_document_failure and job.document_id:
            document = session.get(Document, int(job.document_id))
            if document is not None:
                normalized_path = self._document_normalized_path(document)
                normalized = legacy_db.normalization_failure_stub(
                    normalized_path,
                    original_name=str(document.original_name),
                    notes=message,
                )
                document.normalized_text_path = normalized["path"]
                document.normalized_storage_key = storage_key_from_path(self.settings.upload_root, normalized["path"], Path(normalized["path"]).name)
                document.normalized_status = normalized["status"]
                document.normalized_format = normalized["format"]
                document.normalized_method = normalized["method"]
                document.normalized_notes = normalized["notes"]
                document.normalized_preview = normalized["preview"]
                document.normalized_updated_at = iso_utc(now_dt)
                self._sync_report_source_capture_for_document(session, int(document.id))

    def bootstrap(self) -> dict[str, Any]:
        with self.session_scope() as session:
            stages = session.execute(select(Stage).where(Stage.is_active.is_(True)).order_by(Stage.sequence, Stage.id)).scalars().all()
            bucket_counts = {
                key: int(count)
                for key, count in session.execute(select(Company.bucket, func.count()).group_by(Company.bucket)).all()
            }
            stage_counts = []
            for stage in stages:
                count = int(
                    session.execute(select(func.count()).select_from(Company).where(Company.bucket == "funnel", Company.current_stage_id == stage.id)).scalar_one()
                    or 0
                )
                completed = int(
                    session.execute(select(func.count()).select_from(Report).where(Report.stage_id == stage.id, Report.result != "Draft")).scalar_one()
                    or 0
                )
                stage_counts.append({**self._stage_payload(stage), "count": count, "completed_reports": completed})
            alerts = (
                session.execute(
                    select(MonitoringRule, Company)
                    .join(Company, Company.id == MonitoringRule.company_id)
                    .where(MonitoringRule.triggered.is_(True), Company.bucket == "monitoring")
                    .order_by(MonitoringRule.updated_at.desc())
                    .limit(10)
                )
                .all()
            )
            return {
                "dashboard": {
                    "buckets": [{**bucket, "count": bucket_counts.get(bucket["key"], 0)} for bucket in legacy_db.BUCKETS],
                    "stages": stage_counts,
                "alerts": [self._dashboard_monitoring_payload(rule, company) for rule, company in alerts],
                },
                "settings_summary": {
                    "reports_created_total": int(session.execute(select(func.count()).select_from(Report)).scalar_one() or 0),
                    "sources_uploaded_total": int(session.execute(select(func.count()).select_from(Document)).scalar_one() or 0),
                    "companies_outside_pool_total": int(session.execute(select(func.count()).select_from(Company).where(Company.bucket != "pool")).scalar_one() or 0),
                },
                "stages": [self._stage_payload(stage) for stage in stages],
                "buckets": legacy_db.BUCKETS,
                "report_actions": legacy_db.REPORT_ACTIONS,
            }

    def stages(self) -> dict[str, Any]:
        with self.session_scope() as session:
            rows = session.execute(select(Stage).where(Stage.is_active.is_(True)).order_by(Stage.sequence, Stage.id)).scalars().all()
            return {"stages": [self._stage_payload(stage) for stage in rows]}

    def templates(self) -> dict[str, Any]:
        with self.session_scope() as session:
            rows = (
                session.execute(
                    select(Template, Stage)
                    .join(Stage, Stage.id == Template.stage_id)
                    .where(Template.is_active.is_(True))
                    .order_by(Stage.sequence, Template.name)
                )
                .all()
            )
            return {"templates": [self._template_payload(template, stage, include_markdown=False) for template, stage in rows]}

    def template(self, template_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            row = (
                session.execute(select(Template, Stage).join(Stage, Stage.id == Template.stage_id).where(Template.id == template_id).limit(1))
                .first()
            )
            if row is None:
                raise KeyError("Template not found.")
            template, stage = row
            return {"template": self._template_payload(template, stage)}

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
        with self.session_scope() as session:
            companies = session.execute(select(Company).order_by(Company.id)).scalars().all()
            items = [self._company_payload(session, company, detail=False) for company in companies]
            if bucket:
                items = [item for item in items if item.get("bucket") == bucket]
            if stage_id:
                items = [item for item in items if int(item.get("current_stage_id") or 0) == int(stage_id)]
            if search:
                needle = str(search).lower()
                items = [item for item in items if needle in str(item.get("ticker") or "").lower() or needle in str(item.get("name") or "").lower()]
            total = len(items)
            items = self._sort_companies(items, order)
            safe_page = max(1, int(page or 1))
            safe_per_page = max(1, min(int(per_page or 500), 500))
            offset = (safe_page - 1) * safe_per_page
            paged = items[offset : offset + safe_per_page]
            if bucket == "watchlist":
                for item in paged:
                    item["monitoring_rules"] = self._monitoring_rules(session, company_id=int(item["id"]))
            return {"companies": paged, "total": total, "page": safe_page, "per_page": safe_per_page}

    def company(self, company_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise KeyError("Company not found.")
            return {"company": self._company_payload(session, company, detail=True)}

    def monitoring(self) -> dict[str, Any]:
        with self.session_scope() as session:
            return {"rules": self._monitoring_rules(session, bucket="monitoring")}

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
        with self.session_scope() as session:
            rows = (
                session.execute(select(Report, Company, Stage).join(Company, Company.id == Report.company_id).join(Stage, Stage.id == Report.stage_id))
                .all()
            )
            items = [
                self._report_summary_payload(session, report, company, stage, include_company=True, include_completed_at=True)
                for report, company, stage in rows
            ]
            if stage_id is not None:
                items = [item for item in items if int(item["stage_id"]) == int(stage_id)]
            if result:
                items = [item for item in items if str(item.get("result") or "") == str(result)]
            if not include_drafts:
                items = [item for item in items if str(item.get("result") or "") != "Draft"]
            if search:
                needle = str(search).lower()
                items = [
                    item
                    for item in items
                    if needle in str(item.get("title") or "").lower()
                    or needle in str(item.get("summary") or "").lower()
                    or needle in str(item.get("report_month") or "").lower()
                    or needle in str(item.get("ticker") or "").lower()
                    or needle in str(item.get("company_name") or "").lower()
                ]
            total = len(items)
            items = self._sort_reports(items, order or "completed_desc")
            safe_page = max(1, int(page or 1))
            safe_per_page = max(1, min(int(per_page or 500), 500))
            offset = (safe_page - 1) * safe_per_page
            return {"reports": items[offset : offset + safe_per_page], "total": total, "page": safe_page, "per_page": safe_per_page}

    def report(self, report_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            return {"report": self._report_payload(session, report_id)}

    def create_company(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticker = str(payload.get("ticker", "")).strip().upper()
        if not ticker:
            raise ValueError("Ticker is required.")
        name = str(payload.get("name", "")).strip() or ticker
        timestamp = now_utc()
        with self.session_scope() as session:
            company = Company(
                id=self._next_id(session, Company),
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
        return self.company(company_id)

    def update_company(self, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_scope() as session:
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
        return self.company(company_id)

    def save_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_utc()
        stage_id = int(payload["stage_id"])
        markdown = str(payload.get("markdown") or "")
        schema = legacy_db.template_schema(markdown)
        with self.session_scope() as session:
            stage = session.get(Stage, stage_id)
            stage_key = str(stage.key) if stage is not None else ""
            template_candidate = {
                "id": payload.get("id") or "pending",
                "stage_key": stage_key,
                "schema": schema,
            }
            legacy_db.validate_scalar_payload(payload.get("name", ""), "name must be plain text.")
            from app.integrity import assert_no_critical_issues
            from app.integrity import audit_template_record

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
            active_templates = session.execute(select(Template).where(Template.stage_id == stage_id, Template.is_active.is_(True))).scalars().all()
            for template in active_templates:
                template.is_active = False
                template.updated_at = timestamp
            template = Template(
                id=self._next_id(session, Template),
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
        return self.template(template_id)

    def delete_template(self, template_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            template = session.get(Template, template_id)
            if template is None:
                raise KeyError("Template not found.")
            timestamp = now_utc()
            references = int(session.execute(select(func.count()).select_from(Report).where(Report.template_id == template_id)).scalar_one() or 0)
            if references:
                template.is_active = False
                template.updated_at = timestamp
            else:
                session.delete(template)
            session.commit()
        return {"ok": True}

    def create_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        company_id = int(payload["company_id"])
        report_month = str(payload.get("report_month") or datetime.now().strftime("%B %Y"))
        with self.session_scope() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise KeyError("Company not found.")
            template_id = payload.get("template_id")
            template: Template | None = session.get(Template, int(template_id)) if template_id else None
            if template_id and template is None:
                raise ValueError("Template not found.")
            requested_stage_id = payload.get("stage_id")
            stage_id = int(requested_stage_id) if requested_stage_id not in (None, "") else None
            if template is not None:
                if stage_id is not None and int(template.stage_id) != stage_id:
                    raise ValueError("template_id must belong to the selected stage.")
                stage_id = int(template.stage_id)
            else:
                stage_id = stage_id or (int(company.current_stage_id) if company.current_stage_id is not None else None)
                if stage_id is None:
                    first_stage = session.execute(select(Stage).where(Stage.is_active.is_(True)).order_by(Stage.sequence, Stage.id).limit(1)).scalars().first()
                    if first_stage is None:
                        raise ValueError("At least one active stage is required before creating reports.")
                    stage_id = int(first_stage.id)
                template = (
                    session.execute(select(Template).where(Template.stage_id == stage_id, Template.is_active.is_(True)).order_by(Template.version.desc(), Template.id.desc()).limit(1))
                    .scalars()
                    .first()
                )
            if template is None:
                raise ValueError("No active template exists for this stage.")
            stage = session.get(Stage, stage_id)
            stage_name = str(stage.name) if stage is not None else "Report"
            title = str(payload.get("title") or f"{stage_name} {report_month}")
            timestamp = now_utc()
            report = Report(
                id=self._next_id(session, Report),
                workspace_id=1,
                public_id=f"report-{company_id}-{stage_id}-{int(timestamp.timestamp())}",
                company_id=company_id,
                stage_id=stage_id,
                template_id=int(template.id),
                title=title,
                slug=slugify(title, f"report-{company_id}-{stage_id}"),
                report_month=report_month,
                revision=1,
                responses_json={},
                metrics_json={},
                section_ratings_json={},
                data_quality_json={},
                field_sources_json={},
                field_notes_json={},
                field_exceptions_json={},
                result="Draft",
                summary="",
                watchlist_conditions="",
                watchlist_objective_rules_json=[],
                watchlist_subjective_rules="",
                archive_red_flags="",
                next_action="",
                review_date="",
                completed_at="",
                created_by="",
                updated_by="",
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(report)
            session.flush()
            if company.bucket == "pool":
                company.bucket = "funnel"
                company.current_stage_id = stage_id
                company.updated_at = timestamp
            lightweight = self._lightweight_report_payload(session, int(report.id))
            with self._patched_latest_completed_report(session):
                inherited_responses, _, _, _, _, _ = legacy_db.auto_inherited_state(None, lightweight)
            if inherited_responses:
                report.responses_json = inherited_responses
            session.commit()
            report_id = int(report.id)
        return self.report(report_id)

    def preview_report(self, report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_scope() as session:
            report = self._report_payload(session, report_id)
            context = self._report_update_context(report, payload)
            preview = context["completion_candidate"]
            return {
                "completion": context["completion"],
                "preview": {
                    "result": preview.get("result", ""),
                    "summary": preview.get("summary", ""),
                    "watchlist_conditions": preview.get("watchlist_conditions", ""),
                    "archive_red_flags": preview.get("archive_red_flags", ""),
                    "next_action": preview.get("next_action", ""),
                    "review_date": preview.get("review_date", ""),
                },
            }

    def update_report(self, report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_scope() as session:
            current_payload = self._report_payload(session, report_id)
            context = self._report_update_context(current_payload, payload)
            if context["enforce_completion_gate"] and context["completion"]["status"] != "complete":
                raise legacy_db.ReportCompletionBlocked(context["completion"])
            report = session.get(Report, report_id)
            if report is None:
                raise KeyError("Report not found.")
            write_payload = dict(context["payload"])
            write_payload.pop("completed_at", None)
            if context["desired_objective_rules"] is not None:
                write_payload["watchlist_objective_rules"] = legacy_db.stored_objective_rules(context["desired_objective_rules"])
            write_payload["result"] = context["persisted_result"]
            timestamp_dt = now_utc()
            timestamp = iso_utc(timestamp_dt)
            for key in ("title", "report_month", "result", "summary", "watchlist_conditions", "watchlist_subjective_rules", "archive_red_flags", "next_action", "review_date"):
                if key in write_payload:
                    setattr(report, key, write_payload.get(key) or "")
            json_fields = {
                "responses": "responses_json",
                "metrics": "metrics_json",
                "section_ratings": "section_ratings_json",
                "data_quality": "data_quality_json",
                "field_sources": "field_sources_json",
                "field_notes": "field_notes_json",
                "field_exceptions": "field_exceptions_json",
                "watchlist_objective_rules": "watchlist_objective_rules_json",
            }
            for source_key, attr_name in json_fields.items():
                if source_key in write_payload:
                    setattr(report, attr_name, write_payload.get(source_key))
            if context["finalize"] and context["requested_result"] in legacy_db.REPORT_ACTIONS:
                report.completed_at = timestamp
            report.revision = int(report.revision or 1) + 1
            report.updated_at = timestamp_dt
            if context["finalize"] and context["requested_result"] in legacy_db.REPORT_ACTIONS:
                self._apply_report_result(session, report, write_payload["result"])
            self._sync_report_monitoring_rules(
                session,
                report_id=report_id,
                company_id=int(report.company_id),
                result=write_payload["result"],
                desired_rules=context["desired_objective_rules"],
            )
            session.commit()
        return self.report(report_id)

    def delete_report(self, report_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            report = session.get(Report, report_id)
            if report is None:
                raise KeyError("Report not found.")
            company_id = int(report.company_id)
            for rule in session.execute(select(MonitoringRule).where(MonitoringRule.report_id == report_id)).scalars().all():
                session.delete(rule)
            session.delete(report)
            self._reconcile_company_position(session, company_id)
            session.commit()
        return self.company(company_id)

    def document_status(self, document_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise KeyError("Document not found.")
            payload = self._document_payload(document)
            return {
                "document": {
                    "id": int(payload["id"]),
                    "normalized_status": payload["normalized_status"],
                    "normalized_format": payload.get("normalized_format", ""),
                    "normalized_method": payload.get("normalized_method", ""),
                    "normalized_notes": payload.get("normalized_notes", ""),
                    "normalized_preview": payload.get("normalized_preview", ""),
                    "normalized_text_path": payload.get("normalized_text_path", ""),
                    "normalized_available": bool(payload.get("normalized_available")),
                    "normalized_updated_at": payload.get("normalized_updated_at", ""),
                    "status_url": payload.get("status_url", ""),
                    "download_url": payload.get("download_url", ""),
                    "normalized_url": payload.get("normalized_url", ""),
                }
            }

    def document_record(self, document_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise KeyError("Document not found.")
            return {"document": self._document_payload(document)}

    def upload_documents(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = list(payload.get("files") or [])
        if not files:
            raise ValueError("At least one file is required.")
        company_id = int(payload["company_id"])
        report_id = int(payload["report_id"]) if payload.get("report_id") else None
        notes = str(payload.get("notes") or "")
        storage = self._storage()
        created_ids: list[int] = []
        with self.session_scope() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise KeyError("Company not found.")
            if report_id is not None:
                report = session.get(Report, report_id)
                if report is None:
                    raise KeyError("Report not found.")
                if int(report.company_id) != company_id:
                    raise ValueError("report_id must belong to the same company.")
            for item in files:
                document = self._create_document_record(
                    session,
                    company_id=company_id,
                    original_name=item["filename"],
                    content=item["content"],
                    report_id=report_id,
                    notes=notes,
                    mime_type=str(item.get("mime_type", "") or ""),
                )
                created_ids.append(int(document.id))
            session.commit()
            documents = [self._document_payload(session.get(Document, document_id)) for document_id in created_ids]
        for document_id in created_ids:
            with self.session_scope() as session:
                document = session.get(Document, document_id)
                if document is not None:
                    storage.mirror_document_record(self._document_payload(document))
        return {"documents": documents}

    def save_report_source(
        self,
        payload: dict[str, Any],
        *,
        file_name: str | None = None,
        file_content: bytes | None = None,
        file_mime_type: str = "",
        file_origin: str = "",
    ) -> dict[str, Any]:
        source_report_id = int(payload["report_id"]) if payload.get("report_id") else None
        has_file = bool(file_name and file_content is not None)
        storage = self._storage()
        created_document_id: int | None = None
        with self.session_scope() as session:
            existing_source = session.get(ReportSource, int(payload["id"])) if payload.get("id") else None
            if payload.get("id") and existing_source is None:
                raise KeyError("Source not found.")
            if existing_source is not None:
                source_report_id = int(existing_source.report_id)
            if source_report_id is None:
                raise ValueError("report_id is required.")
            ctx = self._report_context_row(session, source_report_id)
            document_id = payload.get("document_id") or (int(existing_source.document_id) if existing_source and existing_source.document_id is not None else None)
            title = str(
                payload.get("title")
                or (existing_source.title if existing_source is not None else "")
                or file_name
                or payload.get("url")
                or (existing_source.url if existing_source is not None else "")
                or "Untitled source"
            ).strip()
            source_type = str(payload.get("source_type", existing_source.source_type if existing_source is not None else "") or "")
            evidence_grade = str(payload.get("evidence_grade", existing_source.evidence_grade if existing_source is not None else "") or "")
            confidence = str(payload.get("confidence", existing_source.confidence if existing_source is not None else "") or "")
            url = str(payload.get("url", existing_source.url if existing_source is not None else "") or "")
            canonical_url = legacy_db.canonicalize_source_url(url)
            tags = legacy_db.normalize_tags(payload.get("tags", list(existing_source.tags_json or []) if existing_source is not None else []))
            snapshot_guidance_acknowledged = legacy_db.parse_boolean_flag(
                payload.get(
                    "snapshot_guidance_acknowledged",
                    bool(existing_source.snapshot_guidance_acknowledged) if existing_source is not None else False,
                ),
                field_name="snapshot_guidance_acknowledged",
            )
            link_only_reason = str(payload.get("link_only_reason", existing_source.link_only_reason if existing_source is not None else "") or "").strip()
            citation = str(payload.get("citation", existing_source.citation if existing_source is not None else "") or "")
            notes = str(payload.get("notes", existing_source.notes if existing_source is not None else "") or "")
            if evidence_grade and evidence_grade not in {"F", "O", "M", "I", "V"}:
                raise ValueError("Invalid evidence grade.")
            if confidence and confidence not in {"High", "Medium", "Low"}:
                raise ValueError("Invalid confidence value.")
            if url and not document_id and not has_file:
                if not snapshot_guidance_acknowledged:
                    raise ValueError("URL-only sources require snapshot_guidance_acknowledged=true after reading the snapshot upload guidance.")
                if not link_only_reason:
                    raise ValueError("URL-only sources require link_only_reason explaining why no snapshot was uploaded.")
            capture_document: Document | None = None
            if has_file and file_name and file_content is not None:
                capture_document = self._create_document_record(
                    session,
                    company_id=int(ctx.company.id),
                    original_name=file_name,
                    content=file_content,
                    report_id=source_report_id,
                    notes=notes,
                    mime_type=file_mime_type,
                )
                document_id = int(capture_document.id)
                created_document_id = int(capture_document.id)
            elif document_id:
                capture_document = session.get(Document, int(document_id))
                if capture_document is None:
                    raise KeyError("Document not found.")
                if int(capture_document.company_id) != int(ctx.company.id):
                    raise ValueError("Sources can only link to documents from the same company.")
            capture_kind = legacy_db.inferred_capture_kind(
                capture_kind=file_origin or (existing_source.capture_kind if existing_source is not None else ""),
                document_id=document_id,
                url=url,
            )
            capture_state = legacy_db.SOURCE_CAPTURE_LINK_ONLY
            capture_error = ""
            if document_id:
                doc_payload = self._document_payload(capture_document)
                capture_state, capture_error = legacy_db.source_capture_state_for_document(doc_payload)
                snapshot_guidance_acknowledged = bool(existing_source.snapshot_guidance_acknowledged) if existing_source is not None else False
            timestamp = now_utc()
            if existing_source is not None:
                existing_source.document_id = int(document_id) if document_id else None
                existing_source.title = title
                existing_source.capture_kind = capture_kind
                existing_source.source_type = source_type
                existing_source.evidence_grade = evidence_grade
                existing_source.confidence = confidence
                existing_source.tags_json = tags
                existing_source.url = url
                existing_source.canonical_url = canonical_url
                existing_source.link_only_reason = link_only_reason
                existing_source.snapshot_guidance_acknowledged = bool(snapshot_guidance_acknowledged)
                existing_source.capture_state = capture_state
                existing_source.capture_error = capture_error
                existing_source.citation = citation
                existing_source.notes = notes
                existing_source.updated_at = timestamp
                source = existing_source
            else:
                source = ReportSource(
                    id=self._next_id(session, ReportSource),
                    workspace_id=1,
                    report_id=source_report_id,
                    document_id=int(document_id) if document_id else None,
                    title=title,
                    capture_kind=capture_kind,
                    source_type=source_type,
                    evidence_grade=evidence_grade,
                    confidence=confidence,
                    tags_json=tags,
                    url=url,
                    canonical_url=canonical_url,
                    link_only_reason=link_only_reason,
                    snapshot_guidance_acknowledged=bool(snapshot_guidance_acknowledged),
                    capture_state=capture_state,
                    capture_error=capture_error,
                    citation=citation,
                    notes=notes,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(source)
                session.flush()
            if document_id:
                self._sync_report_source_capture_for_document(session, int(document_id))
            session.commit()
            source_id = int(source.id)
        if created_document_id is not None:
            with self.session_scope() as session:
                document = session.get(Document, created_document_id)
                if document is not None:
                    storage.mirror_document_record(self._document_payload(document))
        with self.session_scope() as session:
            source = session.get(ReportSource, source_id)
            ctx = self._report_context_row(session, int(source.report_id))
            document = session.get(Document, int(source.document_id)) if source.document_id is not None else None
            return {"source": self._source_payload(source, report=ctx.report, stage=ctx.stage, document=document)}

    def delete_report_source(self, source_id: int) -> dict[str, Any]:
        with self.session_scope() as session:
            source = session.get(ReportSource, source_id)
            if source is None:
                raise KeyError("Source not found.")
            source_key = str(source_id)
            reports = session.execute(select(Report)).scalars().all()
            for report in reports:
                field_sources = dict(report.field_sources_json or {})
                changed = False
                for entry in field_sources.values():
                    if not isinstance(entry, dict):
                        continue
                    source_ids = list(entry.get("source_ids") or [])
                    filtered = [item for item in source_ids if str(item) != source_key]
                    if filtered != source_ids:
                        entry["source_ids"] = filtered
                        changed = True
                if changed:
                    report.field_sources_json = field_sources
                    report.revision = int(report.revision or 1) + 1
                    report.updated_at = now_utc()
            session.delete(source)
            session.commit()
        return {"ok": True}

    def _save_monitoring_rule_in_session(
        self,
        session: Any,
        payload: dict[str, Any],
        *,
        allow_report_owned_structure: bool = False,
    ) -> MonitoringRule:
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
        if existing and existing.report_id and not allow_report_owned_structure:
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
        triggered = legacy_db.evaluate_rule(comparator, current_number, threshold_number)
        timestamp_dt = now_utc()
        timestamp = iso_utc(timestamp_dt)
        if existing is not None:
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
            return existing
        rule = MonitoringRule(
            id=self._next_id(session, MonitoringRule),
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
        session.flush()
        return rule

    def save_monitoring_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_scope() as session:
            rule = self._save_monitoring_rule_in_session(session, payload)
            session.commit()
            company = session.get(Company, int(rule.company_id))
            result = self._monitoring_payload(rule, company)
        for key in ("ticker", "company_name"):
            result.pop(key, None)
        return {"rule": result}

    def process_next_background_job(self, worker_id: str, *, lease_seconds: int = legacy_db.DEFAULT_JOB_LEASE_SECONDS) -> bool:
        with self.session_scope() as session:
            job = self._lease_background_job(session, worker_id, lease_seconds=lease_seconds)
            if job is None:
                return False
            job_id = int(job.id)
            session.commit()
        storage = self._storage()
        try:
            with self.session_scope() as session:
                job = session.get(BackgroundJob, job_id)
                if job is None:
                    return False
                if str(job.kind or "") != legacy_db.JOB_KIND_DOCUMENT_NORMALIZATION:
                    self._fail_job(session, job, message=f"Unsupported background job kind: {job.kind}", update_document_failure=False)
                    session.commit()
                    return True
                document = session.get(Document, int(job.document_id or 0))
                if document is None:
                    self._fail_job(session, job, message="Document not found for background normalization job.", update_document_failure=False)
                    session.commit()
                    return True
                storage_path = self._document_local_path(document)
                normalized_path = self._document_normalized_path(document)
                if storage_path.exists():
                    normalized = normalize_document_file(
                        storage_path,
                        normalized_path,
                        original_name=str(document.original_name),
                        mime_type=str(document.mime_type or ""),
                    )
                else:
                    normalized = legacy_db.normalization_failure_stub(
                        normalized_path,
                        original_name=str(document.original_name),
                        notes="Stored artifact is missing.",
                    )
                document.normalized_text_path = str(normalized["path"])
                document.normalized_storage_key = storage_key_from_path(self.settings.upload_root, normalized["path"], Path(normalized["path"]).name)
                document.normalized_status = normalized["status"]
                document.normalized_format = normalized["format"]
                document.normalized_method = normalized["method"]
                document.normalized_notes = normalized["notes"]
                document.normalized_preview = normalized["preview"]
                document.normalized_updated_at = iso_utc(now_utc())
                self._sync_report_source_capture_for_document(session, int(document.id))
                job.status = legacy_db.JOB_STATUS_COMPLETED
                job.leased_by = ""
                job.leased_at = ""
                job.last_error = ""
                job.completed_at = iso_utc(now_utc())
                job.updated_at = now_utc()
                session.commit()
                storage.mirror_document_record(self._document_payload(document))
                if str(self.settings.backend_mode) == "postgres_verify":
                    legacy_db.process_next_background_job(self.settings.sqlite_path, self.settings.upload_root, worker_id)
                return True
        except Exception as exc:
            with self.session_scope() as session:
                job = session.get(BackgroundJob, job_id)
                if job is not None:
                    self._fail_job(session, job, message=str(exc), update_document_failure=True)
                    session.commit()
                    if job.document_id:
                        document = session.get(Document, int(job.document_id))
                        if document is not None:
                            storage.mirror_document_record(self._document_payload(document))
            return True
