from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

V1_ROOT = Path(__file__).resolve().parents[4]
if str(V1_ROOT) not in sys.path:
    sys.path.insert(0, str(V1_ROOT))

from funnel_app import db as legacy_db

CRITICAL_SEVERITY = "critical"
WARNING_SEVERITY = "warning"


@dataclass(slots=True)
class IntegrityIssue:
    severity: str
    code: str
    entity: str
    entity_id: str
    message: str
    path: str = ""
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "entity": self.entity,
            "entity_id": self.entity_id,
            "message": self.message,
            "path": self.path,
            "details": self.details or {},
        }


def _issue(
    severity: str,
    code: str,
    entity: str,
    entity_id: Any,
    message: str,
    *,
    path: str = "",
    details: dict[str, Any] | None = None,
) -> IntegrityIssue:
    return IntegrityIssue(
        severity=severity,
        code=code,
        entity=entity,
        entity_id=str(entity_id),
        message=message,
        path=path,
        details=details,
    )


def critical_issues(issues: list[IntegrityIssue]) -> list[IntegrityIssue]:
    return [issue for issue in issues if issue.severity == CRITICAL_SEVERITY]


def issues_to_dicts(issues: list[IntegrityIssue]) -> list[dict[str, Any]]:
    return [issue.as_dict() for issue in issues]


def assert_no_critical_issues(issues: list[IntegrityIssue], *, context: str) -> None:
    critical = critical_issues(issues)
    if not critical:
        return
    preview = "; ".join(f"{item.code}: {item.message}" for item in critical[:5])
    raise ValueError(f"{context} failed integrity validation with {len(critical)} critical issue(s): {preview}")


def _template_schema(template: dict[str, Any]) -> dict[str, Any]:
    raw_schema = template.get("schema")
    if isinstance(raw_schema, dict) and raw_schema.get("sections"):
        return legacy_db.schema_with_catalog(raw_schema, stage_key=str(template.get("stage_key") or ""))
    return legacy_db.stored_template_schema(template)


def _label_base(label: str) -> str:
    text = str(label or "").strip()
    if " - " not in text:
        return text
    return text.rsplit(" - ", 1)[0].strip()


def _compat_duplicate_field_id(fields: list[dict[str, Any]]) -> bool:
    if len(fields) < 2:
        return False
    labels = [str(field.get("label") or "").strip() for field in fields]
    paths = [str(field.get("path") or "").strip() for field in fields]
    if len({label for label in labels if label}) != len(labels):
        return False
    if len({path for path in paths if path}) != len(paths):
        return False
    base_labels = {_label_base(label) for label in labels if label}
    return len(base_labels) == 1


def audit_template_record(template: dict[str, Any], *, strict: bool = False) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    template_id = template.get("id", "unknown")
    schema = _template_schema(template)
    sections = list(schema.get("sections") or [])
    fields = list(schema.get("fields") or [])

    if not sections:
        issues.append(
            _issue(
                CRITICAL_SEVERITY,
                "missing_sections",
                "template",
                template_id,
                "Template schema has no sections.",
            )
        )
    if not fields:
        issues.append(
            _issue(
                CRITICAL_SEVERITY,
                "missing_fields",
                "template",
                template_id,
                "Template schema has no fields.",
            )
        )

    seen_section_ids: set[str] = set()
    for index, section in enumerate(sections):
        section_id = str(section.get("id") or "").strip()
        title = str(section.get("title") or "").strip()
        if not section_id:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "missing_section_id",
                    "template",
                    template_id,
                    "Section is missing a stable id.",
                    path=f"sections[{index}]",
                    details={"title": title},
                )
            )
        elif section_id in seen_section_ids:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "duplicate_section_id",
                    "template",
                    template_id,
                    f"Duplicate section id: {section_id}",
                    path=f"sections[{index}]",
                )
            )
        seen_section_ids.add(section_id)

    fields_by_id: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        field_id = str(field.get("id") or "").strip()
        if field_id:
            fields_by_id.setdefault(field_id, []).append(field)

    seen_field_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, field in enumerate(fields):
        field_id = str(field.get("id") or "").strip()
        field_label = str(field.get("label") or "").strip()
        field_path = str(field.get("path") or "").strip()
        field_kind = str(field.get("kind") or "").strip().lower()
        if not field_id:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "missing_field_id",
                    "template",
                    template_id,
                    f"Field `{field_label or index}` is missing a stable id.",
                    path=f"fields[{index}]",
                )
            )
        elif field_id in seen_field_ids:
            duplicate_group = fields_by_id.get(field_id, [])
            duplicate_severity = (
                WARNING_SEVERITY if (not strict and _compat_duplicate_field_id(duplicate_group)) else CRITICAL_SEVERITY
            )
            issues.append(
                _issue(
                    duplicate_severity,
                    "duplicate_field_id",
                    "template",
                    template_id,
                    f"Duplicate field id: {field_id}",
                    path=f"fields[{index}]",
                    details={
                        "field_label": field_label,
                        "compatibility_preserved": duplicate_severity == WARNING_SEVERITY,
                    },
                )
            )
        seen_field_ids.add(field_id)

        if not field_label:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "missing_field_label",
                    "template",
                    template_id,
                    f"Field `{field_id or index}` is missing a label.",
                    path=f"fields[{index}]",
                )
            )

        if not field_path:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "missing_field_path",
                    "template",
                    template_id,
                    f"Field `{field_label or field_id}` is missing a path.",
                    path=f"fields[{index}]",
                )
            )
        elif field_path in seen_paths:
            issues.append(
                _issue(
                    WARNING_SEVERITY,
                    "duplicate_field_path",
                    "template",
                    template_id,
                    f"Duplicate field path: {field_path}",
                    path=f"fields[{index}]",
                    details={"field_id": field_id},
                )
            )
        seen_paths.add(field_path)

        if field_kind == "select":
            options = [str(option).strip() for option in (field.get("options") or [])]
            if not options:
                issues.append(
                    _issue(
                        CRITICAL_SEVERITY,
                        "missing_select_options",
                        "template",
                        template_id,
                        f"Field `{field_label or field_id}` is selectable but has no options.",
                        path=f"fields[{index}]",
                    )
                )
            if any(not option for option in options):
                issues.append(
                    _issue(
                        CRITICAL_SEVERITY,
                        "blank_select_option",
                        "template",
                        template_id,
                        f"Field `{field_label or field_id}` contains a blank option label.",
                        path=f"fields[{index}].options",
                    )
                )
            duplicates = sorted({option for option in options if options.count(option) > 1})
            if duplicates:
                issues.append(
                    _issue(
                        CRITICAL_SEVERITY,
                        "duplicate_select_option",
                        "template",
                        template_id,
                        f"Field `{field_label or field_id}` contains duplicate option labels.",
                        path=f"fields[{index}].options",
                        details={"duplicates": duplicates},
                    )
                )
        if field_kind == "checkbox":
            options = [str(option).strip() for option in (field.get("options") or [])]
            if any(not option for option in options):
                issues.append(
                    _issue(
                        WARNING_SEVERITY,
                        "blank_checkbox_option",
                        "template",
                        template_id,
                        f"Checkbox field `{field_label or field_id}` contains a blank compatibility option label.",
                        path=f"fields[{index}].options",
                    )
                )

    duplicate_labels = list((schema.get("field_lookup") or {}).get("duplicate_labels") or [])
    if duplicate_labels:
        issues.append(
            _issue(
                WARNING_SEVERITY,
                "duplicate_labels",
                "template",
                template_id,
                "Template contains duplicate labels that can confuse UI summaries or operator review.",
                details={"labels": duplicate_labels},
            )
        )
    return issues


def audit_report_record(report: dict[str, Any]) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    report_id = report.get("id", "unknown")
    template = report.get("template") or {}
    schema = _template_schema(template)
    lookup = legacy_db.field_lookup(schema)
    section_lookup = set((schema.get("section_lookup") or {}).keys())
    metric_ids = {field_id for field_id, field in lookup.items() if legacy_db.metric_field(field)}
    response_ids = set(lookup) - metric_ids
    inherited_response_ids = {str(field_id) for field_id in (report.get("auto_inherited_fields") or [])}
    annotation_keys = set(lookup) | {f"section:{section_id}" for section_id in section_lookup}
    source_ids = {
        str(source.get("id"))
        for source in [
            *(report.get("sources") or []),
            *(report.get("company_sources") or []),
            *(report.get("suggested_sources") or []),
        ]
        if source.get("id") is not None
    }

    for field_id in report.get("responses", {}):
        if field_id not in response_ids and field_id not in inherited_response_ids:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_response_field",
                    "report",
                    report_id,
                    f"Response store references unknown or non-response field `{field_id}`.",
                    path=f"responses.{field_id}",
                )
            )
    for field_id in report.get("metrics", {}):
        if field_id not in metric_ids:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_metric_field",
                    "report",
                    report_id,
                    f"Metric store references unknown or non-metric field `{field_id}`.",
                    path=f"metrics.{field_id}",
                )
            )
    for section_id in report.get("section_ratings", {}):
        if section_id not in section_lookup:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_section_rating",
                    "report",
                    report_id,
                    f"Section ratings reference unknown section `{section_id}`.",
                    path=f"section_ratings.{section_id}",
                )
            )
    for section_id in report.get("data_quality", {}):
        if section_id not in section_lookup:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_data_quality_section",
                    "report",
                    report_id,
                    f"Data quality references unknown section `{section_id}`.",
                    path=f"data_quality.{section_id}",
                )
            )

    for field_id, entry in dict(report.get("field_sources") or {}).items():
        if field_id not in annotation_keys:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_annotation_key",
                    "report",
                    report_id,
                    f"field_sources references unknown field or section `{field_id}`.",
                    path=f"field_sources.{field_id}",
                )
            )
            continue
        if not isinstance(entry, dict):
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "invalid_annotation_value",
                    "report",
                    report_id,
                    f"field_sources entry for `{field_id}` must be an object.",
                    path=f"field_sources.{field_id}",
                )
            )
            continue
        source_refs = entry.get("source_ids") or []
        if not isinstance(source_refs, list):
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "invalid_annotation_source_ids",
                    "report",
                    report_id,
                    f"field_sources `{field_id}` has a non-list source_ids value.",
                    path=f"field_sources.{field_id}.source_ids",
                )
            )
        else:
            missing = [str(source_id) for source_id in source_refs if str(source_id) not in source_ids]
            if missing:
                issues.append(
                    _issue(
                        CRITICAL_SEVERITY,
                        "orphaned_source_binding",
                        "report",
                        report_id,
                        f"field_sources `{field_id}` references source ids that are not available in the report/company source library.",
                        path=f"field_sources.{field_id}.source_ids",
                        details={"missing_source_ids": missing},
                    )
                )

    for field_id in dict(report.get("field_notes") or {}):
        if field_id not in annotation_keys:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_note_key",
                    "report",
                    report_id,
                    f"field_notes references unknown field or section `{field_id}`.",
                    path=f"field_notes.{field_id}",
                )
            )
    for field_id, status in dict(report.get("field_exceptions") or {}).items():
        if field_id not in lookup:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_exception_field",
                    "report",
                    report_id,
                    f"field_exceptions references unknown field `{field_id}`.",
                    path=f"field_exceptions.{field_id}",
                )
            )
            continue
        if legacy_db.normalize_field_exception_status(status) == "":
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "invalid_exception_value",
                    "report",
                    report_id,
                    f"field_exceptions contains an invalid value for `{field_id}`.",
                    path=f"field_exceptions.{field_id}",
                )
            )

    readonly = {str(field_id) for field_id in (report.get("agent_contract", {}).get("readonly_field_ids") or [])}
    for field_id in sorted(readonly):
        if field_id not in lookup:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_readonly_field",
                    "report",
                    report_id,
                    f"agent_contract.readonly_field_ids references unknown field `{field_id}`.",
                    path=f"agent_contract.readonly_field_ids[{field_id}]",
                )
            )

    auto_inherited = {str(field_id) for field_id in (report.get("auto_inherited_fields") or [])}
    for field_id in sorted(auto_inherited):
        if field_id not in lookup:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "unknown_inherited_field",
                    "report",
                    report_id,
                    f"auto_inherited_fields references unknown field `{field_id}`.",
                    path=f"auto_inherited_fields[{field_id}]",
                )
            )

    try:
        normalized_rules = legacy_db.normalize_objective_rules(report.get("watchlist_objective_rules") or [])
        if len(normalized_rules) != len(report.get("watchlist_objective_rules") or []):
            issues.append(
                _issue(
                    WARNING_SEVERITY,
                    "sparse_objective_rules",
                    "report",
                    report_id,
                    "watchlist_objective_rules contains sparse entries that collapse during normalization.",
                )
            )
    except Exception as exc:
        issues.append(
            _issue(
                CRITICAL_SEVERITY,
                "invalid_objective_rules",
                "report",
                report_id,
                f"watchlist_objective_rules failed normalization: {exc}",
                path="watchlist_objective_rules",
            )
        )

    for marker in ("agent_contract", "completion", "workflow", "company_sources", "suggested_sources"):
        if marker not in report:
            issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "missing_runbook_surface",
                    "report",
                    report_id,
                    f"Report payload is missing required surface `{marker}`.",
                    path=marker,
                )
            )

    return issues


def audit_connection(conn: sqlite3.Connection, *, dataset_label: str) -> dict[str, Any]:
    template_rows = legacy_db.list_templates(conn)
    report_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM reports ORDER BY id").fetchall()]
    template_issues: list[IntegrityIssue] = []
    report_issues: list[IntegrityIssue] = []

    for template in template_rows:
        template_issues.extend(audit_template_record(template))
    for report_id in report_ids:
        report = legacy_db.get_report(conn, report_id)
        if report is None:
            report_issues.append(
                _issue(
                    CRITICAL_SEVERITY,
                    "missing_report_record",
                    "report",
                    report_id,
                    "Report id was listed but get_report returned no payload.",
                )
            )
            continue
        report_issues.extend(audit_report_record(report))

    issues = [*template_issues, *report_issues]
    return {
        "dataset": dataset_label,
        "templates": len(template_rows),
        "reports": len(report_ids),
        "issue_count": len(issues),
        "critical_issue_count": len(critical_issues(issues)),
        "issues": issues_to_dicts(issues),
    }


def diff_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=False) != json.dumps(right, sort_keys=True, ensure_ascii=False)
