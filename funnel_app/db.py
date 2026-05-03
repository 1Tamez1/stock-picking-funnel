from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .config import load_seed_config, resolve_app_path
from .document_normalizer import normalize_document_file
from .template_parser import parse_markdown_template, slugify, stable_id


RESULT_PROCEED = "Proceed to Next Step"
RESULT_WATCHLIST = "Watchlist"
RESULT_ARCHIVE = "Archive"
RESULT_RETURN_BUSINESS = "Return to Business Underwriting"
RESULT_RETURN_MANAGEMENT = "Return to Management Underwriting"
RESULT_RETURN_FINANCIAL = "Return to Financial Underwriting"
RESULT_RETURN_VALUATION = "Return to Valuation and Position Size"

BUCKETS = [
    {"key": "pool", "name": "Company Pool"},
    {"key": "funnel", "name": "Funnel"},
    {"key": "monitoring", "name": "Monitoring"},
    {"key": "watchlist", "name": "Watchlist"},
    {"key": "archive", "name": "Archive"},
]

REPORT_ACTIONS = [
    RESULT_PROCEED,
    RESULT_WATCHLIST,
    RESULT_ARCHIVE,
    RESULT_RETURN_BUSINESS,
    RESULT_RETURN_MANAGEMENT,
    RESULT_RETURN_FINANCIAL,
    RESULT_RETURN_VALUATION,
]

FIELD_EXCEPTION_UNKNOWN = "unknown"
FIELD_EXCEPTION_NOT_DISCLOSED = "not_disclosed"
FIELD_EXCEPTION_NOT_APPLICABLE = "not_applicable"
FIELD_EXCEPTION_STATUSES = {
    FIELD_EXCEPTION_UNKNOWN,
    FIELD_EXCEPTION_NOT_DISCLOSED,
    FIELD_EXCEPTION_NOT_APPLICABLE,
}
STRICT_OVERRIDE_MIN_WORDS = 20
STRICT_OVERRIDE_MIN_CHARS = 120
NOTE_PLACEHOLDERS = {
    "selection": "Explain why this option was chosen, what evidence supports it, and what nearly changed the call.",
    "metric": "State the basis, calculation, units or period, and any estimate or caveat behind this datapoint.",
    "date": "State where this date comes from, what it refers to, and any timing caveat.",
    "structured_text": "State the factual basis, scope, and any formatting, unit, or derivation caveat behind this datapoint.",
    "optional_text": "Optional: capture caveats, uncertainty, assumptions, or audit-trail context for this response.",
}
SCHEMA_VERSION = 4
SQLITE_TIMEOUT_SECONDS = 10.0
SQLITE_BUSY_TIMEOUT_MS = 5_000
WRITE_RETRY_ATTEMPTS = 4
WRITE_RETRY_BASE_DELAY_SECONDS = 0.05
DOCUMENT_STATUS_PENDING = "pending"
DOCUMENT_STATUS_READY = "ready"
DOCUMENT_STATUS_LIMITED = "limited"
DOCUMENT_STATUS_FAILED = "failed"
DOCUMENT_STATUSES = {
    DOCUMENT_STATUS_PENDING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUS_LIMITED,
    DOCUMENT_STATUS_FAILED,
}
SOURCE_CAPTURE_LINK_ONLY = "link_only"
SOURCE_CAPTURE_PENDING = "pending"
SOURCE_CAPTURE_READY = "ready"
SOURCE_CAPTURE_LIMITED = "limited"
SOURCE_CAPTURE_FAILED = "failed"
SOURCE_CAPTURE_STATES = {
    SOURCE_CAPTURE_LINK_ONLY,
    SOURCE_CAPTURE_PENDING,
    SOURCE_CAPTURE_READY,
    SOURCE_CAPTURE_LIMITED,
    SOURCE_CAPTURE_FAILED,
}
JOB_KIND_DOCUMENT_NORMALIZATION = "document_normalization"
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_RETRYABLE_STATUSES = {JOB_STATUS_PENDING, JOB_STATUS_RUNNING}
DEFAULT_JOB_LEASE_SECONDS = 60
MAX_JOB_ATTEMPTS = 3


def _manual_note_paths(value: str) -> frozenset[str]:
    return frozenset(line.strip() for line in value.strip().splitlines() if line.strip())


TEXT_NOTE_REQUIRED_PATHS_BY_STAGE: dict[str, frozenset[str]] = {
    "screening": _manual_note_paths(
        """
        if-it-passes-screening.valuation-and-position-size-issue
        """
    ),
    "business_underwriting": _manual_note_paths(
        """
        final-decision.main-question-for-valuation-and-position-size
        if-it-passes-business-underwriting.valuation-and-position-size-issue
        one-page-business-underwriting-conclusion.main-valuation-and-position-size-caution
        """
    ),
    "management_underwriting": _manual_note_paths(
        """
        if-it-passes-management-underwriting.valuation-and-position-size-issue
        """
    ),
    "financial_underwriting": _manual_note_paths(
        """
        if-it-passes-financial-underwriting.valuation-and-position-size-issue
        one-page-financial-underwriting-conclusion.main-valuation-and-position-size-task
        """
    ),
    "valuation_position_size": _manual_note_paths(
        """
        inherited-from-financial-underwriting.current-portfolio-weight-if-any
        inherited-from-financial-underwriting.proposed-initial-weight
        inherited-from-financial-underwriting.proposed-full-weight
        inherited-from-financial-underwriting.hard-maximum-weight
        4-conservative-worth-and-price-ladder.conservative-worth-per-share
        4-conservative-worth-and-price-ladder.base-worth-per-share
        4-conservative-worth-and-price-ladder.high-worth-per-share
        4-conservative-worth-and-price-ladder.clearly-cheap-enough-to-size-up
        4-conservative-worth-and-price-ladder.too-expensive-even-if-the-business-is-excellent
        4-conservative-worth-and-price-ladder.answer
        2-range-and-sensitivity-table.conservative-value-share
        2-range-and-sensitivity-table.conservative-3-year-return-from-current-price
        2-range-and-sensitivity-table.base-value-share
        2-range-and-sensitivity-table.base-3-year-return-from-current-price
        2-range-and-sensitivity-table.favorable-value-share
        2-range-and-sensitivity-table.favorable-3-year-return-from-current-price
        2-range-and-sensitivity-table.permanent-loss-guardrail-value-share
        2-range-and-sensitivity-table.permanent-loss-guardrail-3-year-return-from-current-price
        1-sizing-inputs.knowability-of-value-range
        1-sizing-inputs.business-quality-durability
        1-sizing-inputs.balance-sheet-resilience
        1-sizing-inputs.range-width-valuation-uncertainty
        1-sizing-inputs.downside-asymmetry
        1-sizing-inputs.buyback-issuance-dilution-discipline
        1-sizing-inputs.portfolio-correlation
        1-sizing-inputs.opportunity-cost
        1-sizing-inputs.proposed-initial-weight
        1-sizing-inputs.proposed-full-weight
        1-sizing-inputs.hard-maximum-weight
        3-buy-add-and-no-buy-boundaries.attractive-starter-buy-range
        3-buy-add-and-no-buy-boundaries.clearly-cheap-enough-to-size-up
        3-buy-add-and-no-buy-boundaries.no-buy-above
        3-buy-add-and-no-buy-boundaries.add-only-if
        3-buy-add-and-no-buy-boundaries.full-position-only-if
        3-buy-add-and-no-buy-boundaries.return-to-underwriting-if
        final-decision.business-category
        final-decision.conservative-worth-per-share
        final-decision.base-worth-per-share
        final-decision.high-worth-per-share
        final-decision.clearly-cheap-enough-to-size-up
        final-decision.too-expensive-even-if-the-business-is-excellent
        final-decision.discount-premium-to-conservative-worth
        final-decision.proposed-initial-weight
        final-decision.proposed-full-weight
        final-decision.hard-maximum-weight
        final-decision.next-funnel-stage
        if-it-is-approved-for-execution.attractive-starter-buy-range
        if-it-is-approved-for-execution.clearly-cheap-enough-to-size-up
        if-it-is-approved-for-execution.no-buy-above
        if-it-is-approved-for-execution.starter-size
        if-it-is-approved-for-execution.full-position-conditions
        if-it-is-approved-for-execution.return-to-underwriting-conditions
        if-it-is-approved-for-execution.liquidity-order-type-considerations
        one-page-valuation-and-position-size-conclusion.primary-valuation-method
        one-page-valuation-and-position-size-conclusion.conservative-worth-per-share
        one-page-valuation-and-position-size-conclusion.clearly-cheap-enough-to-size-up
        one-page-valuation-and-position-size-conclusion.too-expensive-even-if-the-business-is-excellent
        one-page-valuation-and-position-size-conclusion.margin-of-safety-view
        one-page-valuation-and-position-size-conclusion.expected-return-without-rerating
        one-page-valuation-and-position-size-conclusion.downside-view
        one-page-valuation-and-position-size-conclusion.position-size-view
        """
    ),
    "execution_rules": _manual_note_paths(
        """
        1-master-snapshot-table.primary-listing-adr-local-line-value
        1-master-snapshot-table.quote-currency-reporting-currency-value
        1-master-snapshot-table.quote-date-and-time-value
        1-master-snapshot-table.current-share-price-value
        1-master-snapshot-table.diluted-shares-outstanding-value
        1-master-snapshot-table.market-cap-value
        1-master-snapshot-table.net-debt-net-cash-value
        1-master-snapshot-table.enterprise-value-value
        1-master-snapshot-table.existing-position-size-value
        1-master-snapshot-table.existing-cost-basis-value
        1-master-snapshot-table.conservative-worth-per-share-value
        1-master-snapshot-table.base-worth-per-share-value
        1-master-snapshot-table.high-worth-per-share-value
        1-master-snapshot-table.attractive-starter-buy-range-value
        1-master-snapshot-table.clearly-cheap-enough-to-size-up-value
        1-master-snapshot-table.no-buy-above-line-value
        1-master-snapshot-table.proposed-starter-size-value
        1-master-snapshot-table.proposed-full-size-value
        1-master-snapshot-table.hard-max-size-value
        1-master-snapshot-table.latest-annual-report-reviewed-value
        1-master-snapshot-table.latest-quarterly-report-reviewed-value
        1-master-snapshot-table.next-earnings-key-event-value
        1-master-snapshot-table.date-of-last-valuation-and-position-size-memo-value
        1-master-snapshot-table.analyst-last-updated-value
        1-buy-zone-design.what-exact-price-or-range-qualifies-for-a-starter-buy
        1-buy-zone-design.what-exact-price-or-range-qualifies-for-a-size-up-buy
        1-buy-zone-design.what-is-the-absolute-no-buy-above-line-for-fresh-buying
        1-buy-zone-design.what-price-drop-would-force-a-return-to-underwriting-before-any-add-is-a
        1-buy-zone-design.what-exact-discount-to-conservative-worth-justifies-the-first-purchase
        1-buy-zone-design.if-the-current-price-is-below-the-approved-range-is-that-a-gift-a-warnin
        2-order-construction.what-order-style-will-be-used-limit-staged-limits-manual-accumulation-vw
        2-order-construction.how-many-tranches-are-planned
        2-order-construction.what-is-the-maximum-capital-to-deploy-in-one-day-or-one-session
        2-order-construction.what-is-the-maximum-percentage-of-average-daily-volume-or-average-daily-
        2-order-construction.will-orders-avoid-the-open-close-or-abnormal-spread-periods
        2-order-construction.if-the-security-is-illiquid-what-spread-tolerance-or-partial-fill-behavi
        2-order-construction.if-both-adr-and-local-line-trade-which-line-should-be-used
        1-trigger-table.business-review-deadline
        1-trigger-table.management-review-deadline
        1-trigger-table.financial-review-deadline
        1-trigger-table.portfolio-liquidity-correct-stage
        1-trigger-table.valuation-price-review-deadline
        1-trigger-table.portfolio-liquidity-review-deadline
        1-trigger-table.governance-legal-control-review-deadline
        1-trigger-table.capital-allocation-review-deadline
        1-trigger-table.financing-balance-sheet-review-deadline
        too-hard-to-execute.execution-pattern-result
        final-decision.execution-pattern
        final-decision.quote-date-and-time
        final-decision.conservative-worth-per-share
        final-decision.base-worth-per-share
        final-decision.high-worth-per-share
        final-decision.attractive-starter-buy-range
        final-decision.clearly-cheap-enough-to-size-up
        final-decision.no-buy-above-line
        final-decision.existing-weight
        final-decision.new-target-weight
        final-decision.hard-max-weight
        final-decision.planned-order-construction
        one-page-execution-conclusion.execution-pattern
        one-page-execution-conclusion.conservative-worth-per-share
        one-page-execution-conclusion.base-worth-per-share
        one-page-execution-conclusion.high-worth-per-share
        one-page-execution-conclusion.attractive-starter-buy-range
        one-page-execution-conclusion.clearly-cheap-enough-to-size-up
        one-page-execution-conclusion.no-buy-above-line
        one-page-execution-conclusion.current-discount-or-premium-to-conservative-worth
        one-page-execution-conclusion.existing-position
        one-page-execution-conclusion.target-weight
        one-page-execution-conclusion.hard-max-weight
        one-page-execution-conclusion.order-plan
        one-page-execution-conclusion.hold-rule
        one-page-execution-conclusion.trim-rule
        one-page-execution-conclusion.exit-rule
        one-page-execution-conclusion.main-monitoring-focus
        if-it-executes-now.starter-size
        if-it-executes-now.full-size-conditions
        if-it-executes-now.hard-maximum
        if-it-executes-now.immediate-cancel-condition
        if-it-executes-now.monitoring-trigger-before-next-add
        if-it-enters-staged-orders.number-of-tranches
        if-it-enters-staged-orders.maximum-time-between-tranche-reviews
        if-it-enters-staged-orders.invalidation-rule-that-stops-the-ladder
        if-it-enters-staged-orders.monitoring-trigger-between-tranches
        if-it-holds-existing.no-fresh-buy-condition
        if-it-holds-existing.trim-condition
        if-it-holds-existing.exit-condition
        if-it-holds-existing.next-review-trigger
        """
    ),
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@contextmanager
def savepoint(conn: sqlite3.Connection, prefix: str = "sp"):
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {name}")


def confirmation_reader(prompt: str) -> str:
    return input(prompt)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def database_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return SCHEMA_VERSION
    if isinstance(row, sqlite3.Row):
        return int(row[0] or 0)
    return int(row[0] or 0)


def transient_sqlite_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and (
        "database is locked" in message
        or "database table is locked" in message
        or "database is busy" in message
        or "busy" in message
    )


def retry_busy(operation: Callable[[], Any], *, attempts: int = WRITE_RETRY_ATTEMPTS) -> Any:
    delay = WRITE_RETRY_BASE_DELAY_SECONDS
    last_error: sqlite3.Error | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return operation()
        except sqlite3.Error as exc:
            if not transient_sqlite_error(exc) or attempt >= attempts:
                raise
            last_error = exc
            time.sleep(delay)
            delay *= 2
    if last_error is not None:
        raise last_error
    return None


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def dump_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


class ReportRevisionConflict(Exception):
    def __init__(self, report_id: int, current_revision: int, updated_at: str) -> None:
        self.report_id = report_id
        self.current_revision = current_revision
        self.updated_at = updated_at
        super().__init__("Report changed since it was opened. Reload the latest version and retry.")


class ReportCompletionBlocked(Exception):
    def __init__(self, completion: dict[str, Any], message: str | None = None) -> None:
        self.completion = completion
        super().__init__(
            message
            or "Report cannot be finalized until every non-exempt field is covered, sourced, and note requirements are satisfied."
        )


def template_structure_backup_root(
    conn: sqlite3.Connection,
    backup_root: Path | None = None,
) -> Path:
    if backup_root is not None:
        root = backup_root
    else:
        row = conn.execute("PRAGMA database_list").fetchone()
        database_file = Path(row["file"]).resolve() if row and row["file"] else Path.cwd() / "var" / "funnel.db"
        root = database_file.parent / "report_structure_backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def template_structure_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    stages = [
        row_to_dict(row)
        for row in conn.execute(
            "SELECT id, key, name, description, sequence, is_active FROM stages ORDER BY sequence, id"
        ).fetchall()
        if row
    ]
    templates: list[dict[str, Any]] = []
    rows = conn.execute(
        """
        SELECT templates.*, stages.key AS stage_key, stages.name AS stage_name, stages.sequence AS stage_sequence,
               COUNT(reports.id) AS report_count
        FROM templates
        JOIN stages ON stages.id = templates.stage_id
        LEFT JOIN reports ON reports.template_id = templates.id
        GROUP BY templates.id
        ORDER BY stages.sequence, templates.version, templates.id
        """
    ).fetchall()
    for row in rows:
        item = row_to_dict(row)
        schema = load_json(item.get("schema_json"), {})
        item["field_count"] = int(schema.get("field_count") or 0)
        item["section_count"] = int(schema.get("section_count") or 0)
        item["markdown_length"] = len(item.get("markdown") or "")
        templates.append(item)
    return {
        "captured_at": now_iso(),
        "stages": stages,
        "templates": templates,
    }


def create_template_structure_backup(
    conn: sqlite3.Connection,
    *,
    action: str,
    backup_root: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    token = uuid.uuid4().hex[:8]
    stem = f"{stamp}-{slugify(action) or 'template-structure'}-{token}"
    root = template_structure_backup_root(conn, backup_root)
    database_path = root / f"{stem}.sqlite3"
    manifest_path = root / f"{stem}.json"

    destination = sqlite3.connect(database_path)
    try:
        conn.backup(destination)
    finally:
        destination.close()

    manifest = {
        "action": action,
        "metadata": metadata or {},
        "database_backup_path": str(database_path),
        "structure_snapshot": template_structure_snapshot(conn),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "database_backup_path": str(database_path),
        "structure_manifest_path": str(manifest_path),
    }


def require_template_structure_confirmation(
    action: str,
    *,
    summary_lines: list[str] | None = None,
    auto_confirm: bool = False,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> None:
    if auto_confirm:
        return

    reader = input_fn or confirmation_reader
    writer = output_fn or print
    if input_fn is None and not sys.stdin.isatty():
        raise RuntimeError(
            f"{action} requires two interactive confirmations because it changes report structure. "
            "Re-run in a terminal so you can confirm it interactively."
        )

    if summary_lines:
        writer(f"WARNING: {action} will change the active report/template structure.")
        for line in summary_lines:
            writer(f"WARNING: {line}")
    else:
        writer(f"WARNING: {action} will change the active report/template structure.")

    first = reader("WARNING: Type 'I UNDERSTAND' to continue: ")
    if first.strip().upper() != "I UNDERSTAND":
        raise RuntimeError(f"{action} cancelled at first confirmation.")

    writer(
        "WARNING: A full backup of the current report structure will be created before anything is written, "
        "but restoring it is still a manual recovery step."
    )
    second = reader("WARNING: Type 'BACKUP THEN APPLY' to continue: ")
    if second.strip().upper() != "BACKUP THEN APPLY":
        raise RuntimeError(f"{action} cancelled at second confirmation.")


def guard_template_structure_change(
    conn: sqlite3.Connection,
    *,
    action: str,
    summary_lines: list[str] | None = None,
    auto_confirm: bool = False,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    backup_root: Path | None = None,
    backup_metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    require_template_structure_confirmation(
        action,
        summary_lines=summary_lines,
        auto_confirm=auto_confirm,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    backup = create_template_structure_backup(
        conn,
        action=action,
        backup_root=backup_root,
        metadata=backup_metadata,
    )
    if output_fn is not None or not auto_confirm:
        writer = output_fn or print
        writer(f"WARNING: Backup saved to {backup['structure_manifest_path']}")
    return backup


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def canonicalize_source_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme and not parsed.netloc:
        return raw

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    netloc = host
    if parsed.username:
        netloc = parsed.username
        if parsed.password:
            netloc += f":{parsed.password}"
        netloc += f"@{host}"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"

    path = parsed.path or ""
    if path == "/":
        path = ""
    elif len(path) > 1:
        path = path.rstrip("/")

    normalized = SplitResult(
        scheme=scheme,
        netloc=netloc,
        path=path,
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def template_schema(markdown: str) -> dict[str, Any]:
    return parse_markdown_template(markdown)


def text_field_requires_notes(stage_key: str, path: str) -> bool:
    return path in TEXT_NOTE_REQUIRED_PATHS_BY_STAGE.get(str(stage_key or "").strip(), frozenset())


def field_note_policy(field: dict[str, Any], *, stage_key: str = "") -> dict[str, Any]:
    kind = str(field.get("kind") or "").strip().lower()
    path = str(field.get("path") or "").strip()
    section_title = normalize_label(field.get("section_title", ""))

    if section_title == "basic inputs" or path.startswith("basic-inputs."):
        return {
            "required": False,
            "category": "optional_text",
            "placeholder": NOTE_PLACEHOLDERS["optional_text"],
        }

    if kind in {"select", "checkbox"}:
        return {
            "required": True,
            "category": "selection",
            "placeholder": NOTE_PLACEHOLDERS["selection"],
        }
    if kind in {"metric", "number"}:
        return {
            "required": True,
            "category": "metric",
            "placeholder": NOTE_PLACEHOLDERS["metric"],
        }
    if kind == "date":
        return {
            "required": True,
            "category": "date",
            "placeholder": NOTE_PLACEHOLDERS["date"],
        }
    if kind in {"text", "textarea"} and text_field_requires_notes(stage_key, path):
        return {
            "required": True,
            "category": "structured_text",
            "placeholder": NOTE_PLACEHOLDERS["structured_text"],
        }
    return {
        "required": False,
        "category": "optional_text",
        "placeholder": NOTE_PLACEHOLDERS["optional_text"],
    }


def add_policy_fields_to_schema(raw_schema: dict[str, Any]) -> dict[str, Any]:
    schema = dict(raw_schema or {})
    sections = [dict(section) for section in schema.get("sections", [])]
    has_hard_gate_summary = any(normalize_label(section.get("title", "")) == "hard gate summary" for section in sections)

    for section in sections:
        section["fields"] = [dict(field) for field in section.get("fields", [])]
        if not has_hard_gate_summary or normalize_label(section.get("title", "")) != "final decision":
            continue
        if any(normalize_label(field.get("label", "")) == "override rationale" for field in section["fields"]):
            continue
        section["fields"].append(
            {
                "id": stable_id(str(section.get("id") or section.get("title") or "final-decision"), "override-rationale"),
                "label": "Override rationale",
                "kind": "textarea",
                "help": (
                    "Required only when the final decision overrides a non-pass hard gate. "
                    "Be specific about the exact gate, why the override is acceptable now, "
                    "what evidence will settle it, and what would reverse the decision."
                ),
            }
        )

    schema["sections"] = sections
    return schema


def schema_with_catalog(raw_schema: dict[str, Any] | None, *, stage_key: str = "") -> dict[str, Any]:
    # The parser stays close to markdown; the catalog adds the stable lookup layer
    # used by the UI, validation, and agent contracts.
    schema = add_policy_fields_to_schema(raw_schema or {})
    sections: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    field_lookup: dict[str, dict[str, Any]] = {}
    by_label: dict[str, list[str]] = {}
    by_normalized: dict[str, list[str]] = {}
    section_lookup: dict[str, dict[str, Any]] = {}

    for section_index, raw_section in enumerate(schema.get("sections", []), start=1):
        section = dict(raw_section)
        section_id = str(section.get("id") or f"section-{section_index}")
        section_title = str(section.get("title") or f"Section {section_index}")
        section_path = slugify(section_title)
        section_fields: list[dict[str, Any]] = []

        for field_index, raw_field in enumerate(raw_section.get("fields", []), start=1):
            field = dict(raw_field)
            field_id = str(field.get("id") or f"{section_id}-field-{field_index}")
            field_label = str(field.get("label") or f"Field {field_index}")
            field["id"] = field_id
            field["label"] = field_label
            field["section_id"] = str(field.get("section_id") or section_id)
            field["section_title"] = section_title
            field["path"] = f"{section_path}.{slugify(field_label)}"
            note_policy = field_note_policy(field, stage_key=stage_key)
            field["ordinal"] = len(fields) + 1
            field["notes_required"] = bool(note_policy["required"])
            field["note_category"] = str(note_policy["category"])
            field["note_placeholder"] = str(note_policy["placeholder"])
            section_fields.append(field)
            fields.append(field)
            field_lookup[field_id] = {
                key: field.get(key)
                for key in (
                    "id",
                    "label",
                    "kind",
                    "help",
                    "options",
                    "max",
                    "origin",
                    "section_id",
                    "section_title",
                    "path",
                    "ordinal",
                    "notes_required",
                    "note_category",
                    "note_placeholder",
                )
            }
            by_label.setdefault(field_label, []).append(field_id)
            by_normalized.setdefault(normalize_label(field_label), []).append(field_id)

        section["id"] = section_id
        section["title"] = section_title
        section["path"] = section_path
        section["fields"] = section_fields
        section["field_ids"] = [field["id"] for field in section_fields]
        sections.append(section)
        section_lookup[section_id] = {
            "id": section_id,
            "title": section_title,
            "level": section.get("level", 0),
            "path": section_path,
            "field_ids": section["field_ids"],
        }

    return {
        **schema,
        "sections": sections,
        "fields": fields,
        "section_count": len(sections),
        "field_count": len(fields),
        "section_lookup": section_lookup,
        "field_lookup": {
            "by_id": field_lookup,
            "by_label": by_label,
            "by_normalized_label": by_normalized,
            "duplicate_labels": sorted(label for label, ids in by_label.items() if len(ids) > 1),
        },
    }


def stored_template_schema(item: dict[str, Any]) -> dict[str, Any]:
    raw_schema = load_json(item.get("schema_json"), {})
    if not isinstance(raw_schema, dict) or not raw_schema.get("sections"):
        raw_schema = template_schema(str(item.get("markdown") or ""))
    return schema_with_catalog(raw_schema, stage_key=str(item.get("stage_key") or ""))


def metric_field(field: dict[str, Any]) -> bool:
    return field.get("kind") in {"metric", "number"}


def raw_field_value_from_stores(field: dict[str, Any], responses: dict[str, Any], metrics: dict[str, Any]) -> Any:
    source = metrics if metric_field(field) else responses
    fallback = responses if metric_field(field) else metrics
    value = source.get(field["id"])
    if value in (None, ""):
        value = fallback.get(field["id"])
    return value


def field_lookup(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(schema.get("field_lookup", {}).get("by_id", {}))


def section_ids(schema: dict[str, Any]) -> set[str]:
    return set((schema.get("section_lookup") or {}).keys())


def is_section_annotation_key(key: str, schema: dict[str, Any]) -> bool:
    return bool(key) and key.startswith("section:") and key.split(":", 1)[1] in section_ids(schema)


def is_valid_annotation_key(key: str, schema: dict[str, Any]) -> bool:
    return key in field_lookup(schema) or is_section_annotation_key(key, schema)


def normalized_source_ids(source_ids: Any, allowed_source_ids: set[str]) -> list[int | str]:
    if not isinstance(source_ids, list):
        return []
    cleaned: list[int | str] = []
    seen: set[str] = set()
    for item in source_ids:
        key = str(item).strip()
        if not key or key in seen or key not in allowed_source_ids:
            continue
        seen.add(key)
        cleaned.append(int(key) if key.isdigit() else key)
    return cleaned


def normalize_field_exception_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in FIELD_EXCEPTION_STATUSES else ""


def normalize_report_state(report: dict[str, Any]) -> dict[str, Any]:
    schema = report.get("template", {}).get("schema", {})
    responses = dict(report.get("responses") or {})
    metrics = dict(report.get("metrics") or {})
    normalized_responses: dict[str, Any] = {}
    normalized_metrics: dict[str, Any] = {}

    # Field kinds can change as templates evolve. Normalize into the bucket the
    # current schema expects so old payloads keep rendering and validating.
    for field in schema.get("fields", []):
        value = raw_field_value_from_stores(field, responses, metrics)
        if value in (None, ""):
            continue
        target = normalized_metrics if metric_field(field) else normalized_responses
        target[field["id"]] = value

    valid_section_ids = section_ids(schema)
    normalized_section_ratings = {
        key: value
        for key, value in dict(report.get("section_ratings") or {}).items()
        if key in valid_section_ids and value not in (None, "")
    }
    normalized_data_quality = {
        key: value
        for key, value in dict(report.get("data_quality") or {}).items()
        if key in valid_section_ids and value not in (None, "")
    }

    allowed_source_ids = {str(source["id"]) for source in (report.get("company_sources") or report.get("sources") or [])}
    normalized_field_sources: dict[str, dict[str, Any]] = {}
    for key, entry in dict(report.get("field_sources") or {}).items():
        if not is_valid_annotation_key(key, schema) or not isinstance(entry, dict):
            continue
        source_ids = normalized_source_ids(entry.get("source_ids"), allowed_source_ids)
        citation = str(entry.get("citation") or "").strip()
        if not source_ids and not citation:
            continue
        normalized_field_sources[key] = {"source_ids": source_ids, "citation": citation}

    normalized_field_notes = {
        key: str(note)
        for key, note in dict(report.get("field_notes") or {}).items()
        if is_valid_annotation_key(key, schema) and str(note or "").strip()
    }

    normalized_field_exceptions = {
        field_id: status
        for field_id, status in (
            (str(field_id), normalize_field_exception_status(status))
            for field_id, status in dict(report.get("field_exceptions") or {}).items()
        )
        if field_id in field_lookup(schema) and status
    }

    return {
        "responses": normalized_responses,
        "metrics": normalized_metrics,
        "section_ratings": normalized_section_ratings,
        "data_quality": normalized_data_quality,
        "field_sources": normalized_field_sources,
        "field_notes": normalized_field_notes,
        "field_exceptions": normalized_field_exceptions,
    }


def merge_patch_map(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def auto_inherited_field_ids(report: dict[str, Any]) -> set[str]:
    return {str(field_id) for field_id in (report.get("auto_inherited_fields") or [])}


def persisted_report_store(report: dict[str, Any], store_name: str) -> dict[str, Any]:
    store = dict(report.get(store_name) or {})
    if store_name in {"responses", "metrics"}:
        for field_id in auto_inherited_field_ids(report):
            store.pop(field_id, None)
    return store


def validate_scalar_payload(value: Any, message: str) -> None:
    if isinstance(value, (dict, list)):
        raise ValueError(message)


def validate_field_value(field: dict[str, Any], value: Any) -> None:
    validate_scalar_payload(value, f"{field['label']} must be a scalar value.")
    text = "" if value is None else str(value)
    if field.get("kind") == "select" and text and text not in (field.get("options") or []):
        raise ValueError(f"{field['label']} must be one of the allowed options.")
    if field.get("kind") == "checkbox" and text.lower() not in {"", "true", "false"}:
        raise ValueError(f"{field['label']} must be true or blank.")


def validate_report_annotations(
    report: dict[str, Any],
    entries: dict[str, Any],
    *,
    notes_only: bool = False,
) -> None:
    schema = report.get("template", {}).get("schema", {})
    allowed_source_ids = {str(source["id"]) for source in (report.get("company_sources") or report.get("sources") or [])}
    for key, value in entries.items():
        if not is_valid_annotation_key(key, schema):
            raise ValueError(f"Unknown field or section key: {key}")
        if notes_only:
            validate_scalar_payload(value, "Field notes must be plain text.")
            continue
        if not isinstance(value, dict):
            raise ValueError("Each field_sources entry must be an object.")
        source_ids = value.get("source_ids") or []
        if not isinstance(source_ids, list):
            raise ValueError("field_sources.source_ids must be a list.")
        for item in source_ids:
            source_id = str(item).strip()
            if not source_id or source_id not in allowed_source_ids:
                raise ValueError(f"Unknown source id linked to {key}: {item}")
        validate_scalar_payload(value.get("citation", ""), "Field source citations must be plain text.")


def validate_report_update_payload(report: dict[str, Any], payload: dict[str, Any]) -> None:
    schema = report.get("template", {}).get("schema", {})
    lookup = field_lookup(schema)
    metric_ids = {field_id for field_id, field in lookup.items() if metric_field(field)}
    response_ids = set(lookup) - metric_ids
    readonly_field_ids = auto_inherited_field_ids(report)

    for store_name, allowed_ids in (("responses", response_ids), ("metrics", metric_ids)):
        entries = payload.get(store_name)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            raise ValueError(f"{store_name} must be an object.")
        for field_id, value in entries.items():
            if field_id not in allowed_ids:
                raise ValueError(f"Unknown or invalid {store_name[:-1]} field id: {field_id}")
            if field_id in readonly_field_ids:
                raise ValueError(f"Field is inherited and read-only: {field_id}")
            validate_field_value(lookup[field_id], value)

    valid_section_ids = section_ids(schema)
    for store_name in ("section_ratings", "data_quality"):
        entries = payload.get(store_name)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            raise ValueError(f"{store_name} must be an object.")
        for section_id, value in entries.items():
            if section_id not in valid_section_ids:
                raise ValueError(f"Unknown section id in {store_name}: {section_id}")
            validate_scalar_payload(value, f"{store_name} values must be scalar for section {section_id}.")

    if "field_sources" in payload:
        if not isinstance(payload["field_sources"], dict):
            raise ValueError("field_sources must be an object.")
        validate_report_annotations(report, payload["field_sources"])

    if "field_notes" in payload:
        if not isinstance(payload["field_notes"], dict):
            raise ValueError("field_notes must be an object.")
        validate_report_annotations(report, payload["field_notes"], notes_only=True)

    if "field_exceptions" in payload:
        entries = payload["field_exceptions"]
        if not isinstance(entries, dict):
            raise ValueError("field_exceptions must be an object.")
        for field_id, status in entries.items():
            if field_id not in lookup:
                raise ValueError(f"Unknown field id in field_exceptions: {field_id}")
            if field_id in readonly_field_ids:
                raise ValueError(f"Field is inherited and read-only: {field_id}")
            normalized_status = normalize_field_exception_status(status)
            if not normalized_status:
                raise ValueError(
                    "field_exceptions values must be one of: unknown, not_disclosed, not_applicable."
                )

    if "watchlist_objective_rules" in payload:
        normalize_objective_rules(payload["watchlist_objective_rules"])

    if "result" in payload and payload["result"] not in {"", "Draft", *REPORT_ACTIONS}:
        raise ValueError("Invalid report result.")


def parse_optional_number(value: Any, *, field_name: str) -> float | None:
    if value in ("", None):
        return None
    validate_scalar_payload(value, f"{field_name} must be a scalar value.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc


def objective_rule_key(metric_name: str, comparator: str, threshold_value: float | None, unit: str) -> str:
    threshold_text = "" if threshold_value is None else format(threshold_value, ".12g")
    return f"rule-{stable_id(metric_name, comparator, threshold_text, unit)}"


def objective_rule_key_from_entry(entry: dict[str, Any]) -> str:
    return objective_rule_key(
        str(entry.get("metric_name") or entry.get("metric") or "").strip(),
        str(entry.get("comparator") or "<=").strip() or "<=",
        parse_optional_number(entry.get("threshold_value"), field_name="threshold_value"),
        str(entry.get("unit") or "").strip(),
    )


def monitoring_rule_report_key(row: dict[str, Any]) -> str:
    report_rule_key = str(row.get("report_rule_key") or "").strip()
    if report_rule_key:
        return report_rule_key
    return objective_rule_key(
        str(row.get("metric_name") or "").strip(),
        str(row.get("comparator") or "<=").strip() or "<=",
        parse_optional_number(row.get("threshold_value"), field_name="threshold_value"),
        str(row.get("unit") or "").strip(),
    )


def normalize_objective_rules(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("watchlist_objective_rules must be a list.")

    rules: list[dict[str, Any]] = []
    seen_rule_keys: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("Each watchlist_objective_rules entry must be an object.")
        metric_name = str(entry.get("metric_name") or entry.get("metric") or "").strip()
        if not metric_name:
            continue
        comparator = str(entry.get("comparator") or "<=").strip() or "<="
        if comparator not in {"<", "<=", ">", ">=", "=", "=="}:
            raise ValueError("Invalid comparator.")
        threshold_value = parse_optional_number(entry.get("threshold_value"), field_name="threshold_value")
        rule_key = str(entry.get("rule_key") or "").strip() or objective_rule_key(
            metric_name,
            comparator,
            threshold_value,
            str(entry.get("unit") or "").strip(),
        )
        if rule_key in seen_rule_keys:
            raise ValueError(f"Duplicate watchlist objective rule rule_key: {rule_key}")
        seen_rule_keys.add(rule_key)

        rules.append(
            {
                "rule_key": rule_key,
                "metric_name": metric_name,
                "comparator": comparator,
                "threshold_value": threshold_value,
                "unit": str(entry.get("unit") or "").strip(),
                "source": str(entry.get("source") or "").strip(),
                "current_value": parse_optional_number(entry.get("current_value"), field_name="current_value"),
                "notes": str(entry.get("notes") or "").strip(),
            }
        )
    return rules


def stored_objective_rules(value: Any) -> list[dict[str, Any]]:
    return [
        {
            "rule_key": rule["rule_key"],
            "metric_name": rule["metric_name"],
            "comparator": rule["comparator"],
            "threshold_value": rule["threshold_value"],
            "unit": rule["unit"],
            "source": rule["source"],
        }
        for rule in normalize_objective_rules(value)
    ]


def merged_report_update_payload(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload)
    for key in ("responses", "metrics", "section_ratings", "data_quality", "field_sources", "field_notes", "field_exceptions"):
        if key not in merged:
            continue
        incoming = merged[key] or {}
        if not isinstance(incoming, dict):
            raise ValueError(f"{key} must be an object.")
        merged[key] = merge_patch_map(persisted_report_store(report, key), incoming)
    return merged


def parse_boolean_flag(value: Any, *, field_name: str) -> bool:
    if value in (None, "", False):
        return False
    if value is True:
        return True
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValueError(f"{field_name} must be a boolean.")


def report_state_with_payload(
    report: dict[str, Any],
    payload: dict[str, Any],
    *,
    persisted_result: str,
) -> dict[str, Any]:
    candidate = dict(report)
    for key in (
        "title",
        "report_month",
        "summary",
        "watchlist_conditions",
        "watchlist_subjective_rules",
        "archive_red_flags",
        "next_action",
        "review_date",
        "watchlist_objective_rules",
        "responses",
        "metrics",
        "section_ratings",
        "data_quality",
        "field_sources",
        "field_notes",
        "field_exceptions",
    ):
        if key in payload:
            candidate[key] = payload[key]
    candidate["result"] = persisted_result
    candidate.update(normalize_report_state(candidate))
    return candidate


def document_links(document_id: int, normalized_available: bool) -> dict[str, str]:
    return {
        "resource_uri": f"funnel://documents/{document_id}",
        "download_url": f"/api/documents/{document_id}/download",
        "status_url": f"/api/documents/{document_id}/status",
        "normalized_url": f"/api/documents/{document_id}/normalized" if normalized_available else "",
        "normalized_resource_uri": f"funnel://documents/{document_id}/normalized" if normalized_available else "",
    }


def normalized_document_status(item: dict[str, Any]) -> str:
    normalized_status = str(item.get("normalized_status") or "").strip().lower()
    if normalized_status in DOCUMENT_STATUSES:
        return normalized_status
    if str(item.get("normalized_text_path") or "").strip():
        return DOCUMENT_STATUS_READY
    return DOCUMENT_STATUS_PENDING


def decorate_document_record(item: dict[str, Any]) -> dict[str, Any]:
    item["normalized_status"] = normalized_document_status(item)
    normalized_available = bool(item.get("normalized_text_path")) and item["normalized_status"] in {
        DOCUMENT_STATUS_READY,
        DOCUMENT_STATUS_LIMITED,
        DOCUMENT_STATUS_FAILED,
    }
    item["normalized_available"] = normalized_available
    item.update(document_links(int(item["id"]), normalized_available))
    return item


def source_capture_state(
    *,
    document_id: Any,
    normalized_status: Any,
    url: str,
    capture_state: str = "",
) -> str:
    stored = str(capture_state or "").strip().lower()
    if stored in SOURCE_CAPTURE_STATES:
        return stored
    if document_id:
        normalized = normalized_document_status({"normalized_status": normalized_status})
        if normalized == DOCUMENT_STATUS_READY:
            return SOURCE_CAPTURE_READY
        if normalized == DOCUMENT_STATUS_LIMITED:
            return SOURCE_CAPTURE_LIMITED
        if normalized == DOCUMENT_STATUS_FAILED:
            return SOURCE_CAPTURE_FAILED
        return SOURCE_CAPTURE_PENDING
    if str(url or "").strip():
        return SOURCE_CAPTURE_LINK_ONLY
    return SOURCE_CAPTURE_FAILED


def source_capture_reason(item: dict[str, Any]) -> tuple[str, str]:
    capture_state = source_capture_state(
        document_id=item.get("document_id"),
        normalized_status=item.get("normalized_status"),
        url=str(item.get("url") or ""),
        capture_state=str(item.get("capture_state") or ""),
    )
    capture_error = str(item.get("capture_error") or "").strip()
    if capture_state == SOURCE_CAPTURE_READY:
        return SOURCE_CAPTURE_READY, "Stored artifact and normalized LLM view available."
    if capture_state == SOURCE_CAPTURE_LIMITED:
        return SOURCE_CAPTURE_LIMITED, "Stored artifact saved, but normalized text is limited. Verify against the original file."
    if capture_state == SOURCE_CAPTURE_PENDING:
        return SOURCE_CAPTURE_PENDING, "Stored artifact saved. Normalized LLM view is still pending."
    if capture_state == SOURCE_CAPTURE_FAILED:
        return SOURCE_CAPTURE_FAILED, capture_error or "Stored artifact saved, but normalization failed. Use the original file for verification."
    if capture_state == SOURCE_CAPTURE_LINK_ONLY:
        return SOURCE_CAPTURE_LINK_ONLY, "URL saved without snapshot; citeable, but not reliably reusable by later stages."
    return SOURCE_CAPTURE_FAILED, "Source is missing both a live link and a stored artifact."


def decorate_source_record(item: dict[str, Any]) -> dict[str, Any]:
    item["resource_uri"] = f"funnel://reports/{item['report_id']}/sources/{item['id']}"
    item["report_url"] = f"/api/reports/{item['report_id']}"
    document_id = item.get("document_id")
    item["normalized_status"] = normalized_document_status(item)
    item["snapshot_guidance_acknowledged"] = bool(item.get("snapshot_guidance_acknowledged"))
    item["link_only_reason"] = str(item.get("link_only_reason") or "")
    normalized_available = bool(item.get("normalized_text_path")) and item["normalized_status"] in {
        DOCUMENT_STATUS_READY,
        DOCUMENT_STATUS_LIMITED,
        DOCUMENT_STATUS_FAILED,
    }
    item["canonical_url"] = canonicalize_source_url(item.get("canonical_url") or item.get("url") or "")
    item["capture_kind"] = inferred_capture_kind(
        capture_kind=str(item.get("capture_kind") or "").strip(),
        document_id=document_id,
        url=str(item.get("url") or ""),
    )
    item["capture_state"] = source_capture_state(
        document_id=document_id,
        normalized_status=item.get("normalized_status"),
        url=str(item.get("url") or ""),
        capture_state=str(item.get("capture_state") or ""),
    )
    if item["capture_state"] == SOURCE_CAPTURE_FAILED and not str(item.get("capture_error") or "").strip():
        item["capture_error"] = str(item.get("normalized_notes") or "").strip()
    else:
        item["capture_error"] = str(item.get("capture_error") or "").strip()
    item["normalized_available"] = normalized_available
    if document_id:
        links = document_links(int(document_id), normalized_available)
        item["document_download_url"] = links["download_url"]
        item["document_status_url"] = links["status_url"]
        item["document_normalized_url"] = links["normalized_url"]
        item["document_resource_uri"] = links["resource_uri"]
        item["document_normalized_resource_uri"] = links["normalized_resource_uri"]
    else:
        item["document_download_url"] = ""
        item["document_status_url"] = ""
        item["document_normalized_url"] = ""
        item["document_resource_uri"] = ""
        item["document_normalized_resource_uri"] = ""
    reusability_status, reusability_reason = source_capture_reason(item)
    item["reusability_status"] = reusability_status
    item["reusability_reason"] = reusability_reason
    return item


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            sequence INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            bucket TEXT NOT NULL DEFAULT 'pool',
            current_stage_id INTEGER REFERENCES stages(id),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            description TEXT NOT NULL DEFAULT '',
            markdown TEXT NOT NULL,
            schema_json TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            stage_id INTEGER NOT NULL REFERENCES stages(id),
            template_id INTEGER NOT NULL REFERENCES templates(id),
            title TEXT NOT NULL,
            report_month TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1,
            responses_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            section_ratings_json TEXT NOT NULL DEFAULT '{}',
            data_quality_json TEXT NOT NULL DEFAULT '{}',
            field_sources_json TEXT NOT NULL DEFAULT '{}',
            field_notes_json TEXT NOT NULL DEFAULT '{}',
            field_exceptions_json TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT 'Draft',
            summary TEXT NOT NULL DEFAULT '',
            watchlist_conditions TEXT NOT NULL DEFAULT '',
            watchlist_objective_rules_json TEXT NOT NULL DEFAULT '[]',
            watchlist_subjective_rules TEXT NOT NULL DEFAULT '',
            archive_red_flags TEXT NOT NULL DEFAULT '',
            next_action TEXT NOT NULL DEFAULT '',
            review_date TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            report_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            normalized_text_path TEXT NOT NULL DEFAULT '',
            normalized_status TEXT NOT NULL DEFAULT '',
            normalized_format TEXT NOT NULL DEFAULT '',
            normalized_method TEXT NOT NULL DEFAULT '',
            normalized_notes TEXT NOT NULL DEFAULT '',
            normalized_preview TEXT NOT NULL DEFAULT '',
            normalized_updated_at TEXT NOT NULL DEFAULT '',
            uploaded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            capture_kind TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            evidence_grade TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            url TEXT NOT NULL DEFAULT '',
            canonical_url TEXT NOT NULL DEFAULT '',
            link_only_reason TEXT NOT NULL DEFAULT '',
            snapshot_guidance_acknowledged INTEGER NOT NULL DEFAULT 0,
            capture_state TEXT NOT NULL DEFAULT '',
            capture_error TEXT NOT NULL DEFAULT '',
            citation TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS background_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            leased_by TEXT NOT NULL DEFAULT '',
            leased_at TEXT NOT NULL DEFAULT '',
            available_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monitoring_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            report_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,
            report_rule_key TEXT NOT NULL DEFAULT '',
            metric_name TEXT NOT NULL,
            comparator TEXT NOT NULL,
            threshold_value REAL,
            unit TEXT NOT NULL DEFAULT '',
            current_value REAL,
            source TEXT NOT NULL DEFAULT '',
            triggered INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            last_checked_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_companies_bucket ON companies(bucket);
        CREATE INDEX IF NOT EXISTS idx_companies_stage ON companies(current_stage_id);
        CREATE INDEX IF NOT EXISTS idx_reports_company ON reports(company_id);
        CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company_id);
        CREATE INDEX IF NOT EXISTS idx_report_sources_report ON report_sources(report_id);
        CREATE INDEX IF NOT EXISTS idx_report_sources_document ON report_sources(document_id);
        CREATE INDEX IF NOT EXISTS idx_background_jobs_status ON background_jobs(status, available_at, id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_background_jobs_kind_document ON background_jobs(kind, document_id);
        CREATE INDEX IF NOT EXISTS idx_monitoring_company ON monitoring_rules(company_id);
        """
    )
    ensure_column(conn, "reports", "revision", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "reports", "field_sources_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "reports", "field_notes_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "reports", "field_exceptions_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "reports", "completed_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_text_path", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_status", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_format", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_method", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_preview", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "documents", "normalized_updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "report_sources", "capture_kind", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "report_sources", "canonical_url", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "report_sources", "link_only_reason", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "report_sources", "snapshot_guidance_acknowledged", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "report_sources", "capture_state", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "report_sources", "capture_error", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "monitoring_rules", "report_rule_key", "TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_completed ON reports(completed_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_report_rule ON monitoring_rules(report_id, report_rule_key)")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    backfill_report_completion_timestamps(conn)
    backfill_document_status_metadata(conn)
    backfill_report_source_metadata(conn)
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def inferred_capture_kind(*, capture_kind: str, document_id: Any, url: str) -> str:
    if capture_kind:
        return capture_kind
    if document_id:
        return "uploaded_file"
    if str(url or "").strip():
        return "link_only"
    return ""


def backfill_document_status_metadata(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, normalized_status, normalized_text_path
        FROM documents
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        item = row_to_dict(row)
        if not item:
            continue
        normalized_status = normalized_document_status(item)
        if normalized_status == str(item.get("normalized_status") or "").strip():
            continue
        conn.execute(
            "UPDATE documents SET normalized_status = ?, normalized_updated_at = COALESCE(NULLIF(normalized_updated_at, ''), ?) WHERE id = ?",
            (normalized_status, now_iso(), int(item["id"])),
        )


def backfill_report_completion_timestamps(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE reports
        SET completed_at = updated_at
        WHERE result != 'Draft' AND COALESCE(completed_at, '') = ''
        """
    )


def source_capture_state_for_document(document: dict[str, Any] | None) -> tuple[str, str]:
    if not document:
        return SOURCE_CAPTURE_FAILED, "Linked document is missing."
    normalized_status = normalized_document_status(document)
    if normalized_status == DOCUMENT_STATUS_READY:
        return SOURCE_CAPTURE_READY, ""
    if normalized_status == DOCUMENT_STATUS_LIMITED:
        return SOURCE_CAPTURE_LIMITED, ""
    if normalized_status == DOCUMENT_STATUS_FAILED:
        return SOURCE_CAPTURE_FAILED, str(document.get("normalized_notes") or "").strip()
    return SOURCE_CAPTURE_PENDING, ""


def sync_report_source_capture_for_document(conn: sqlite3.Connection, document_id: int) -> None:
    document = get_document(conn, document_id)
    capture_state, capture_error = source_capture_state_for_document(document)
    conn.execute(
        """
        UPDATE report_sources
        SET capture_state = ?, capture_error = ?, updated_at = CASE WHEN updated_at = '' THEN ? ELSE updated_at END
        WHERE document_id = ?
        """,
        (capture_state, capture_error, now_iso(), document_id),
    )


def backfill_report_source_metadata(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT report_sources.id, report_sources.document_id, report_sources.url, report_sources.canonical_url,
               report_sources.capture_kind, report_sources.capture_state, report_sources.capture_error,
               documents.normalized_status, documents.normalized_notes
        FROM report_sources
        LEFT JOIN documents ON documents.id = report_sources.document_id
        ORDER BY report_sources.id
        """
    ).fetchall()
    for row in rows:
        item = row_to_dict(row)
        if not item:
            continue
        canonical_url = canonicalize_source_url(item.get("url", ""))
        capture_kind = inferred_capture_kind(
            capture_kind=str(item.get("capture_kind") or "").strip(),
            document_id=item.get("document_id"),
            url=str(item.get("url") or ""),
        )
        capture_state = source_capture_state(
            document_id=item.get("document_id"),
            normalized_status=item.get("normalized_status"),
            url=str(item.get("url") or ""),
            capture_state=str(item.get("capture_state") or ""),
        )
        capture_error = str(item.get("capture_error") or "").strip()
        if capture_state == SOURCE_CAPTURE_FAILED and not capture_error:
            capture_error = str(item.get("normalized_notes") or "").strip()
        if (
            canonical_url == str(item.get("canonical_url") or "").strip()
            and capture_kind == str(item.get("capture_kind") or "").strip()
            and capture_state == str(item.get("capture_state") or "").strip()
            and capture_error == str(item.get("capture_error") or "").strip()
        ):
            continue
        conn.execute(
            """
            UPDATE report_sources
            SET canonical_url = ?, capture_kind = ?, capture_state = ?, capture_error = ?
            WHERE id = ?
            """,
            (canonical_url, capture_kind, capture_state, capture_error, int(item["id"])),
        )


def seed_defaults_plan(conn: sqlite3.Connection, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_seed_config()
    stage_rows = conn.execute("SELECT id, key, name, description, sequence, is_active FROM stages").fetchall()
    stages_by_key = {str(row["key"]): row for row in stage_rows}

    stage_inserts: list[dict[str, Any]] = []
    stage_updates: list[dict[str, Any]] = []
    template_inserts: list[dict[str, Any]] = []
    missing_sources: list[dict[str, str]] = []

    for index, stage in enumerate(config.get("stages", []), start=1):
        sequence = int(stage.get("sequence") or index)
        current = stages_by_key.get(stage["key"])
        desired = {
            "key": stage["key"],
            "name": stage["name"],
            "description": stage.get("description", ""),
            "sequence": sequence,
        }
        if current is None:
            stage_inserts.append(desired)
        elif (
            str(current["name"]) != desired["name"]
            or str(current["description"] or "") != desired["description"]
            or int(current["sequence"]) != desired["sequence"]
            or int(current["is_active"]) != 1
        ):
            stage_updates.append(desired)

    for index, stage in enumerate(config.get("stages", []), start=1):
        sequence = int(stage.get("sequence") or index)
        template_source = resolve_app_path(stage.get("template_source"))
        if not template_source or not template_source.exists():
            if stage.get("template_source"):
                missing_sources.append(
                    {
                        "stage_key": stage["key"],
                        "template_source": str(stage["template_source"]),
                    }
                )
            continue
        current = stages_by_key.get(stage["key"])
        if current is not None:
            existing = conn.execute(
                "SELECT id FROM templates WHERE stage_id = ? AND is_active = 1 LIMIT 1",
                (int(current["id"]),),
            ).fetchone()
            if existing:
                continue
        template_inserts.append(
            {
                "stage_key": stage["key"],
                "stage_name": stage["name"],
                "sequence": sequence,
                "template_name": stage.get("template_name") or f"{stage['name']} Template",
                "template_description": stage.get("template_description", ""),
                "template_source": str(template_source),
            }
        )

    return {
        "stage_inserts": stage_inserts,
        "stage_updates": stage_updates,
        "template_inserts": template_inserts,
        "missing_sources": missing_sources,
        "has_changes": bool(stage_inserts or stage_updates or template_inserts),
    }


def seed_plan_summary(plan: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if plan.get("stage_inserts"):
        lines.append(
            "Stages to insert: "
            + ", ".join(item["key"] for item in plan["stage_inserts"])
        )
    if plan.get("stage_updates"):
        lines.append(
            "Stages to update: "
            + ", ".join(item["key"] for item in plan["stage_updates"])
        )
    if plan.get("template_inserts"):
        lines.append(
            "Templates to seed: "
            + ", ".join(item["stage_key"] for item in plan["template_inserts"])
        )
    if plan.get("missing_sources"):
        lines.append(
            "Template sources missing and skipped: "
            + ", ".join(item["stage_key"] for item in plan["missing_sources"])
        )
    return lines


def seed_defaults(
    conn: sqlite3.Connection,
    *,
    auto_confirm: bool = False,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    config = load_seed_config()
    plan = seed_defaults_plan(conn, config)
    if not plan["has_changes"]:
        return {
            "action": "noop",
            "stage_insert_count": 0,
            "stage_update_count": 0,
            "template_insert_count": 0,
        }

    backup = guard_template_structure_change(
        conn,
        action="Seed default stages and templates",
        summary_lines=seed_plan_summary(plan),
        auto_confirm=auto_confirm,
        input_fn=input_fn,
        output_fn=output_fn,
        backup_root=backup_root,
        backup_metadata=plan,
    )

    timestamp = now_iso()
    for stage in plan["stage_inserts"]:
        conn.execute(
            """
            INSERT INTO stages (key, name, description, sequence, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                stage["key"],
                stage["name"],
                stage["description"],
                int(stage["sequence"]),
                timestamp,
                timestamp,
            ),
        )

    for stage in plan["stage_updates"]:
        conn.execute(
            """
            UPDATE stages
            SET name = ?, description = ?, sequence = ?, is_active = 1, updated_at = ?
            WHERE key = ?
            """,
            (
                stage["name"],
                stage["description"],
                int(stage["sequence"]),
                timestamp,
                stage["key"],
            ),
        )

    stage_ids = {row["key"]: row["id"] for row in conn.execute("SELECT id, key FROM stages")}
    for stage in plan["template_inserts"]:
        markdown = Path(stage["template_source"]).read_text(encoding="utf-8")
        schema = template_schema(markdown)
        conn.execute(
            """
            INSERT INTO templates
            (stage_id, name, version, description, markdown, schema_json, is_active, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, 1, ?, ?)
            """,
            (
                int(stage_ids[stage["stage_key"]]),
                stage["template_name"],
                stage["template_description"],
                markdown,
                dump_json(schema),
                timestamp,
                timestamp,
            ),
        )

    conn.commit()
    return {
        "action": "seeded",
        "stage_insert_count": len(plan["stage_inserts"]),
        "stage_update_count": len(plan["stage_updates"]),
        "template_insert_count": len(plan["template_inserts"]),
        "backup": backup,
    }


def sync_template_schemas(conn: sqlite3.Connection) -> int:
    updated = 0
    rows = conn.execute("SELECT id, markdown, schema_json FROM templates").fetchall()
    for row in rows:
        # markdown is the source of truth; schema_json is just a cached parse.
        fresh_schema = template_schema(row["markdown"])
        if dump_json(fresh_schema) == row["schema_json"]:
            continue
        conn.execute("UPDATE templates SET schema_json = ? WHERE id = ?", (dump_json(fresh_schema), int(row["id"])))
        updated += 1
    conn.commit()
    return updated


def sync_report_payloads(conn: sqlite3.Connection) -> int:
    updated = 0
    rows = conn.execute(
        """
        SELECT id, responses_json, metrics_json, section_ratings_json, data_quality_json, field_sources_json, field_notes_json,
               field_exceptions_json
        FROM reports
        """
    ).fetchall()
    columns = {
        "responses": "responses_json",
        "metrics": "metrics_json",
        "section_ratings": "section_ratings_json",
        "data_quality": "data_quality_json",
        "field_sources": "field_sources_json",
        "field_notes": "field_notes_json",
        "field_exceptions": "field_exceptions_json",
    }
    for row in rows:
        # Re-save against the live schema so parser changes do not strand values in
        # stale field ids or the wrong JSON bucket.
        report = get_report(conn, int(row["id"]))
        if not report:
            continue
        normalized = normalize_report_state(report)
        changed_columns: dict[str, str] = {}
        for key, column in columns.items():
            stored = load_json(row[column], {})
            if stored == normalized[key]:
                continue
            changed_columns[column] = dump_json(normalized[key])
        if not changed_columns:
            continue
        assignments = ", ".join(f"{column} = ?" for column in changed_columns)
        values = list(changed_columns.values()) + [now_iso(), int(row["id"])]
        conn.execute(f"UPDATE reports SET {assignments}, updated_at = ? WHERE id = ?", values)
        updated += 1
    conn.commit()
    return updated


def setup_database(
    db_file: Path,
    *,
    auto_confirm_seed: bool = False,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    backup_root: Path | None = None,
) -> None:
    conn = connect(db_file)
    try:
        init_db(conn)
        seed_defaults(
            conn,
            auto_confirm=auto_confirm_seed,
            input_fn=input_fn,
            output_fn=output_fn,
            backup_root=backup_root,
        )
    finally:
        conn.close()


def list_stages(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM stages WHERE is_active = 1 ORDER BY sequence, id"
    ).fetchall()
    return [row_to_dict(row) for row in rows if row]


def get_next_stage(conn: sqlite3.Connection, stage_id: int) -> dict[str, Any] | None:
    current = conn.execute("SELECT sequence FROM stages WHERE id = ?", (stage_id,)).fetchone()
    if not current:
        return None
    row = conn.execute(
        """
        SELECT * FROM stages
        WHERE is_active = 1 AND sequence > ?
        ORDER BY sequence, id
        LIMIT 1
        """,
        (current["sequence"],),
    ).fetchone()
    return row_to_dict(row)


def first_stage_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM stages WHERE is_active = 1 ORDER BY sequence, id LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def template_summary_item(row: sqlite3.Row) -> dict[str, Any]:
    item = row_to_dict(row) or {}
    item["schema"] = stored_template_schema(item)
    item.pop("schema_json", None)
    item.pop("markdown", None)
    return item


def list_templates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT templates.id, templates.stage_id, templates.name, templates.version, templates.description,
               templates.markdown, templates.schema_json, templates.is_active, templates.created_at, templates.updated_at,
               stages.name AS stage_name, stages.key AS stage_key
        FROM templates
        JOIN stages ON stages.id = templates.stage_id
        WHERE templates.is_active = 1
        ORDER BY stages.sequence, templates.name
        """
    ).fetchall()
    return [template_summary_item(row) for row in rows]


def get_template(conn: sqlite3.Connection, template_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT templates.*, stages.name AS stage_name, stages.key AS stage_key
        FROM templates
        JOIN stages ON stages.id = templates.stage_id
        WHERE templates.id = ?
        """,
        (template_id,),
    ).fetchone()
    item = row_to_dict(row)
    if item:
        item["schema"] = stored_template_schema(item)
        item.pop("schema_json", None)
    return item


def active_template_for_stage(conn: sqlite3.Connection, stage_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT templates.*, stages.name AS stage_name, stages.key AS stage_key
        FROM templates
        JOIN stages ON stages.id = templates.stage_id
        WHERE templates.stage_id = ? AND templates.is_active = 1
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (stage_id,),
    ).fetchone()
    item = row_to_dict(row)
    if item:
        item["schema"] = stored_template_schema(item)
        item.pop("schema_json", None)
    return item


def save_template(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_iso()
    stage_id = int(payload["stage_id"])
    markdown = payload.get("markdown", "")
    schema = template_schema(markdown)
    if payload.get("id"):
        existing = get_template(conn, int(payload["id"]))
        if not existing:
            raise KeyError("Template not found.")
        if int(existing["stage_id"]) != stage_id:
            raise ValueError("Editing an existing template cannot change its stage. Create a new template instead.")
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM templates WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()
    conn.execute(
        "UPDATE templates SET is_active = 0, updated_at = ? WHERE stage_id = ? AND is_active = 1",
        (timestamp, stage_id),
    )
    conn.execute(
        """
        INSERT INTO templates
        (stage_id, name, version, description, markdown, schema_json, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            stage_id,
            payload.get("name", "Untitled Template").strip(),
            int(row["next_version"]),
            payload.get("description", ""),
            markdown,
            dump_json(schema),
            timestamp,
            timestamp,
        ),
    )
    template_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    return get_template(conn, template_id)


def delete_template(conn: sqlite3.Connection, template_id: int) -> None:
    template = get_template(conn, template_id)
    if not template:
        raise KeyError("Template not found.")
    timestamp = now_iso()
    references = conn.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE template_id = ?",
        (template_id,),
    ).fetchone()["count"]
    if references:
        conn.execute(
            "UPDATE templates SET is_active = 0, updated_at = ? WHERE id = ?",
            (timestamp, template_id),
        )
    else:
        conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    conn.commit()


def dashboard(conn: sqlite3.Connection) -> dict[str, Any]:
    bucket_counts = {
        row["bucket"]: row["count"]
        for row in conn.execute(
            "SELECT bucket, COUNT(*) AS count FROM companies GROUP BY bucket"
        ).fetchall()
    }
    stage_counts = []
    for stage in list_stages(conn):
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM companies WHERE bucket = 'funnel' AND current_stage_id = ?",
            (stage["id"],),
        ).fetchone()["count"]
        completed = conn.execute(
            "SELECT COUNT(*) AS count FROM reports WHERE stage_id = ? AND result != 'Draft'",
            (stage["id"],),
        ).fetchone()["count"]
        stage_counts.append({**stage, "count": count, "completed_reports": completed})

    triggered = conn.execute(
        """
        SELECT monitoring_rules.*, companies.ticker, companies.name
        FROM monitoring_rules
        JOIN companies ON companies.id = monitoring_rules.company_id
        WHERE monitoring_rules.triggered = 1 AND companies.bucket = 'monitoring'
        ORDER BY monitoring_rules.updated_at DESC
        LIMIT 10
        """
    ).fetchall()

    return {
        "buckets": [{**bucket, "count": bucket_counts.get(bucket["key"], 0)} for bucket in BUCKETS],
        "stages": stage_counts,
        "alerts": [row_to_dict(row) for row in triggered],
    }


def settings_summary(conn: sqlite3.Connection) -> dict[str, int]:
    reports_created = count_reports(conn, include_drafts=True)
    sources_uploaded_row = conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
    companies_outside_pool_row = conn.execute(
        "SELECT COUNT(*) AS count FROM companies WHERE bucket != 'pool'"
    ).fetchone()
    return {
        "reports_created_total": int(reports_created or 0),
        "sources_uploaded_total": int(sources_uploaded_row["count"]) if sources_uploaded_row else 0,
        "companies_outside_pool_total": int(companies_outside_pool_row["count"]) if companies_outside_pool_row else 0,
    }


def create_company(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    ticker = payload.get("ticker", "").strip().upper()
    if not ticker:
        raise ValueError("Ticker is required.")
    name = payload.get("name", "").strip() or ticker
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO companies (ticker, name, bucket, current_stage_id, notes, created_at, updated_at)
        VALUES (?, ?, 'pool', NULL, ?, ?, ?)
        """,
        (ticker, name, payload.get("notes", ""), timestamp, timestamp),
    )
    conn.commit()
    company_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return get_company(conn, company_id)


def update_company(conn: sqlite3.Connection, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    existing = get_company(conn, company_id)
    if not existing:
        raise KeyError("Company not found.")
    fields = []
    values: list[Any] = []
    for key in ("ticker", "name", "bucket", "current_stage_id", "notes"):
        if key in payload:
            value = payload[key]
            if key == "ticker":
                value = str(value).upper().strip()
            fields.append(f"{key} = ?")
            values.append(value)
    if fields:
        fields.append("updated_at = ?")
        values.append(now_iso())
        values.append(company_id)
        conn.execute(f"UPDATE companies SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    return get_company(conn, company_id)


def company_list_query_parts(
    bucket: str | None = None,
    stage_id: int | None = None,
    search: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    if bucket:
        clauses.append("companies.bucket = ?")
        params.append(bucket)
    if stage_id:
        clauses.append("companies.current_stage_id = ?")
        params.append(stage_id)
    if search:
        clauses.append("(companies.ticker LIKE ? OR companies.name LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def company_list_order_sql(order: str | None = None) -> str:
    mapping = {
        "ticker_asc": "companies.ticker ASC, companies.name ASC",
        "ticker_desc": "companies.ticker DESC, companies.name DESC",
        "name_asc": "companies.name ASC, companies.ticker ASC",
        "name_desc": "companies.name DESC, companies.ticker ASC",
        "review_date_asc": "CASE WHEN COALESCE(latest.review_date, '') = '' THEN 1 ELSE 0 END, latest.review_date ASC, companies.ticker ASC",
        "review_date_desc": "CASE WHEN COALESCE(latest.review_date, '') = '' THEN 1 ELSE 0 END, latest.review_date DESC, companies.ticker ASC",
        "status_asc": "companies.bucket ASC, COALESCE(stages.sequence, 999) ASC, companies.ticker ASC",
        "updated_asc": "companies.updated_at ASC, companies.ticker ASC",
        "updated_desc": "companies.updated_at DESC, companies.ticker ASC",
    }
    return mapping.get(str(order or "updated_desc"), mapping["updated_desc"])


def count_companies(
    conn: sqlite3.Connection,
    bucket: str | None = None,
    stage_id: int | None = None,
    search: str | None = None,
) -> int:
    where, params = company_list_query_parts(bucket=bucket, stage_id=stage_id, search=search)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM companies
        {where}
        """,
        params,
    ).fetchone()
    return int(row["count"]) if row else 0


def list_companies(
    conn: sqlite3.Connection,
    bucket: str | None = None,
    stage_id: int | None = None,
    search: str | None = None,
    *,
    order: str | None = None,
    page: int = 1,
    per_page: int = 500,
) -> list[dict[str, Any]]:
    where, params = company_list_query_parts(bucket=bucket, stage_id=stage_id, search=search)
    safe_page = max(1, int(page or 1))
    safe_per_page = max(1, min(int(per_page or 500), 500))
    offset = (safe_page - 1) * safe_per_page
    order_sql = company_list_order_sql(order)
    rows = conn.execute(
        f"""
        SELECT companies.*, stages.name AS current_stage_name, stages.key AS current_stage_key,
               latest.result AS latest_result,
               latest.summary AS latest_summary,
               latest.review_date AS review_date,
               latest.next_action AS next_action,
               latest.watchlist_conditions AS watchlist_conditions,
               latest.archive_red_flags AS archive_red_flags,
               latest.id AS latest_report_id,
               latest.responses_json AS latest_responses_json,
               latest.metrics_json AS latest_metrics_json,
               latest.template_id AS latest_template_id
        FROM companies
        LEFT JOIN stages ON stages.id = companies.current_stage_id
        LEFT JOIN reports AS latest ON latest.id = (
            SELECT reports.id FROM reports
            WHERE reports.company_id = companies.id
              AND reports.result != 'Draft'
            ORDER BY reports.updated_at DESC, reports.id DESC
            LIMIT 1
        )
        {where}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
        """,
        [*params, safe_per_page, offset],
    ).fetchall()
    companies = [row_to_dict(row) for row in rows if row]
    for company in companies:
        hydrate_company_summary(conn, company)
        if bucket == "watchlist":
            company["monitoring_rules"] = list_monitoring_rules(conn, company_id=int(company["id"]))
    return companies


def get_company(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT companies.*, stages.name AS current_stage_name, stages.key AS current_stage_key,
               latest.result AS latest_result,
               latest.summary AS latest_summary,
               latest.review_date AS review_date,
               latest.next_action AS next_action,
               latest.watchlist_conditions AS watchlist_conditions,
               latest.archive_red_flags AS archive_red_flags,
               latest.id AS latest_report_id,
               latest.responses_json AS latest_responses_json,
               latest.metrics_json AS latest_metrics_json,
               latest.template_id AS latest_template_id
        FROM companies
        LEFT JOIN stages ON stages.id = companies.current_stage_id
        LEFT JOIN reports AS latest ON latest.id = (
            SELECT reports.id FROM reports
            WHERE reports.company_id = companies.id
              AND reports.result != 'Draft'
            ORDER BY reports.updated_at DESC, reports.id DESC
            LIMIT 1
        )
        WHERE companies.id = ?
        """,
        (company_id,),
    ).fetchone()
    item = row_to_dict(row)
    if not item:
        return None
    hydrate_company_summary(conn, item)
    item["reports"] = list_report_summaries(conn, company_id)
    item["documents"] = list_documents(conn, company_id)
    item["company_sources"] = list_company_sources(conn, company_id)
    item["monitoring_rules"] = list_monitoring_rules(conn, company_id=company_id)
    return item


def get_company_metadata(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT companies.id, companies.ticker, companies.name, companies.bucket, companies.current_stage_id,
               companies.created_at, companies.updated_at,
               stages.name AS current_stage_name, stages.key AS current_stage_key
        FROM companies
        LEFT JOIN stages ON stages.id = companies.current_stage_id
        WHERE companies.id = ?
        """,
        (company_id,),
    ).fetchone()
    return row_to_dict(row)


def hydrate_company_summary(conn: sqlite3.Connection, company: dict[str, Any]) -> None:
    report_id = company.pop("latest_report_id", None)
    responses = load_json(company.pop("latest_responses_json", None), {})
    metrics = load_json(company.pop("latest_metrics_json", None), {})
    template_id = company.pop("latest_template_id", None)
    if not report_id or not template_id:
        return
    template = get_template(conn, int(template_id))
    if not template:
        return
    derived = derive_report_summary(template, responses, metrics)
    for key in ("latest_summary", "watchlist_conditions", "archive_red_flags", "next_action", "review_date"):
        if not company.get(key) and derived.get(key):
            company[key] = derived[key]


def derive_report_summary(
    template: dict[str, Any], responses: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, str]:
    if template.get("stage_key") == "screening":
        return screening_summary_data(template.get("schema", {}), responses, metrics)
    return generic_report_summary_data(template.get("schema", {}), responses, metrics)


def field_value_from_report(report: dict[str, Any], field: dict[str, Any]) -> str:
    value = field_value_from_stores(field, report.get("responses", {}), report.get("metrics", {}))
    return value


def field_value_from_stores(field: dict[str, Any], responses: dict[str, Any], metrics: dict[str, Any]) -> str:
    value = raw_field_value_from_stores(field, responses, metrics)
    return str(value).strip() if value not in (None, "") else ""


def get_section(schema: dict[str, Any], title: str) -> dict[str, Any] | None:
    return next((section for section in schema.get("sections", []) if section.get("title") == title), None)


def get_section_field(schema: dict[str, Any], section_title: str, field_label: str) -> dict[str, Any] | None:
    section = get_section(schema, section_title)
    if not section:
        return None
    return next((field for field in section.get("fields", []) if field.get("label") == field_label), None)


def get_field(schema: dict[str, Any], field_label: str, section_title: str | None = None) -> dict[str, Any] | None:
    if section_title:
        field = get_section_field(schema, section_title, field_label)
        if field:
            return field
    return next((field for field in schema.get("fields", []) if field.get("label") == field_label), None)


def source_priority(source: dict[str, Any]) -> float:
    evidence_rank = {"F": 1.0, "O": 0.9, "M": 0.6, "I": 0.5, "V": 0.3}
    confidence_rank = {"High": 1.0, "Medium": 0.7, "Low": 0.4}
    evidence = evidence_rank.get(str(source.get("evidence_grade") or "").upper(), 0.4)
    confidence = confidence_rank.get(str(source.get("confidence") or ""), 0.5)
    return round((evidence + confidence) / 2, 2)


def linked_source_ids(field_sources: dict[str, Any] | None) -> set[str]:
    ids: set[str] = set()
    for entry in dict(field_sources or {}).values():
        if not isinstance(entry, dict):
            continue
        for item in entry.get("source_ids") or []:
            source_id = str(item).strip()
            if source_id:
                ids.add(source_id)
    return ids


def completion_source_warnings(report: dict[str, Any], source_library: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if not source_library:
        warnings.append("No sources have been added to the company source library yet.")
        return warnings

    linked_ids = linked_source_ids(report.get("field_sources"))
    if linked_ids:
        source_map = {str(source["id"]): source for source in source_library}
        cited = [source_map[source_id] for source_id in linked_ids if source_id in source_map]
        if any(source.get("capture_state") == SOURCE_CAPTURE_LINK_ONLY for source in cited):
            warnings.append("Some cited sources are URL-only and will block finalization until a stored snapshot is uploaded.")
        if any(source.get("capture_state") == SOURCE_CAPTURE_PENDING for source in cited):
            warnings.append("Some cited sources are still processing. Wait for normalization to finish before finalizing.")
        if any(source.get("capture_state") == SOURCE_CAPTURE_FAILED for source in cited):
            warnings.append("Some cited sources failed normalization. Replace or repair them before finalizing.")
        if any(source.get("capture_state") == SOURCE_CAPTURE_LIMITED for source in cited):
            warnings.append("Some cited sources have only limited or failed normalized text. Verify against the stored artifact.")

    if not any(source.get("normalized_status") == "ready" for source in source_library if source.get("document_id")):
        warnings.append("No normalized-ready company sources yet. Later-stage reuse will rely on originals or link-only references.")
    return warnings


def suggested_source_sort_key(source: dict[str, Any], *, priority_bucket: int = 2) -> tuple[Any, ...]:
    status_rank = {"ready": 0, "limited": 1, "link_only": 2, "failed": 3}
    updated_at = str(source.get("updated_at") or "")
    try:
        updated_rank = -datetime.fromisoformat(updated_at).timestamp()
    except ValueError:
        updated_rank = 0
    return (
        priority_bucket,
        status_rank.get(str(source.get("reusability_status") or ""), 4),
        -float(source_priority(source)),
        updated_rank,
        -int(source.get("id") or 0),
    )


def merged_report_values(report: dict[str, Any], payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    responses = dict(report.get("responses") or {})
    metrics = dict(report.get("metrics") or {})
    if isinstance(payload, dict):
        if isinstance(payload.get("responses"), dict):
            responses.update(payload["responses"])
        if isinstance(payload.get("metrics"), dict):
            metrics.update(payload["metrics"])
    return responses, metrics


def report_field_has_sources(report: dict[str, Any], field: dict[str, Any]) -> bool:
    entries = report.get("field_sources") or {}
    for key in (field["id"], f"section:{field['section_id']}"):
        entry = entries.get(key)
        if isinstance(entry, dict) and entry.get("source_ids"):
            return True
    return False


def report_field_sources(report: dict[str, Any], field: dict[str, Any], source_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    entries = report.get("field_sources") or {}
    linked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in (field["id"], f"section:{field['section_id']}"):
        entry = entries.get(key)
        if not isinstance(entry, dict):
            continue
        for item in entry.get("source_ids") or []:
            source_id = str(item).strip()
            if not source_id or source_id in seen or source_id not in source_map:
                continue
            seen.add(source_id)
            linked.append(source_map[source_id])
    return linked


def report_source_resources(report: dict[str, Any]) -> list[dict[str, Any]]:
    source_library = report.get("company_sources") or report.get("sources") or []
    suggested_lookup = {str(source["id"]): source for source in (report.get("suggested_sources") or [])}
    resources = []
    for source in source_library:
        source_id = str(source["id"])
        suggested = suggested_lookup.get(source_id) or {}
        resources.append(
            {
                "uri": source["resource_uri"],
                "name": source["title"],
                "kind": "report_source",
                "mime_type": source.get("document_mime_type") or "",
                "normalized_url": source.get("document_normalized_url", ""),
                "download_url": source.get("document_download_url", ""),
                "annotations": {
                    "audience": ["assistant", "user"],
                    "priority": max(source_priority(source), 0.95 if suggested else 0.0),
                    "last_modified": source.get("updated_at", ""),
                    "source_id": int(source["id"]),
                    "report_id": int(source.get("report_id") or 0) if source.get("report_id") else 0,
                    "report_title": source.get("report_title", ""),
                    "stage_name": source.get("stage_name", ""),
                    "stage_key": source.get("stage_key", ""),
                    "reusability_status": source.get("reusability_status", ""),
                    "reusability_reason": source.get("reusability_reason", ""),
                    "suggested_for_reuse": bool(suggested),
                    "suggestion_reason": suggested.get("suggestion_reason", ""),
                },
            }
        )
    return resources


def workflow_report_resources(report: dict[str, Any]) -> list[dict[str, Any]]:
    resources = []
    for previous in report.get("workflow", {}).get("previous_reports", []):
        resources.append(
            {
                "uri": previous["resource_uri"],
                "name": previous["title"],
                "kind": "workflow_report",
                "mime_type": "application/json",
                "api_url": previous["api_url"],
                "annotations": {
                    "audience": ["assistant", "user"],
                    "priority": 0.95 if previous.get("is_latest_for_stage") else 0.75,
                    "last_modified": previous.get("updated_at", ""),
                    "stage_key": previous.get("stage_key", ""),
                    "result": previous.get("result", ""),
                    "is_latest_for_stage": bool(previous.get("is_latest_for_stage")),
                },
            }
        )
    return resources


def inherited_report_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in (
            report.get("inherited_screening"),
            report.get("inherited_business_underwriting"),
            report.get("inherited_management_underwriting"),
            report.get("inherited_financial_underwriting"),
            report.get("inherited_valuation_position_size"),
        )
        if isinstance(item, dict)
    ]


def agent_suggested_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(source["id"]),
            "title": source.get("title", ""),
            "report_id": int(source.get("report_id") or 0) if source.get("report_id") else 0,
            "report_title": source.get("report_title", ""),
            "stage_name": source.get("stage_name", ""),
            "stage_key": source.get("stage_key", ""),
            "source_type": source.get("source_type", ""),
            "evidence_grade": source.get("evidence_grade", ""),
            "confidence": source.get("confidence", ""),
            "reusability_status": source.get("reusability_status", ""),
            "reusability_reason": source.get("reusability_reason", ""),
            "suggestion_reason": source.get("suggestion_reason", ""),
            "resource_uri": source.get("resource_uri", ""),
            "report_url": source.get("report_url", ""),
            "normalized_url": source.get("document_normalized_url", ""),
            "download_url": source.get("document_download_url", ""),
            "url": source.get("url", ""),
            "canonical_url": source.get("canonical_url", ""),
            "citation": source.get("citation", ""),
        }
        for source in (report.get("suggested_sources") or [])
    ]


def agent_field_summary(field: dict[str, Any], *, readonly_field_ids: set[str] | None = None) -> dict[str, Any]:
    readonly = field["id"] in (readonly_field_ids or set())
    item = {
        "id": field["id"],
        "label": field["label"],
        "kind": field["kind"],
        "section_id": field["section_id"],
        "section_title": field.get("section_title", ""),
        "path": field.get("path", ""),
        "help": field.get("help", ""),
        "notes_required": bool(field.get("notes_required")),
        "note_category": field.get("note_category", ""),
        "note_placeholder": field.get("note_placeholder", ""),
    }
    if field.get("options"):
        item["options"] = list(field["options"])
    if field.get("max") not in (None, ""):
        item["max"] = field["max"]
    if field.get("origin"):
        item["origin"] = field["origin"]
    if readonly:
        item["read_only"] = True
        item["annotations_allowed"] = True
    return item


def agent_fillable_sections(schema: dict[str, Any], *, readonly_field_ids: set[str] | None = None) -> list[dict[str, Any]]:
    sections = []
    for section in schema.get("sections", []):
        fields = [agent_field_summary(field, readonly_field_ids=readonly_field_ids) for field in section.get("fields", [])]
        sections.append(
            {
                "id": section["id"],
                "title": section["title"],
                "path": section.get("path", ""),
                "field_count": len(fields),
                "fields": fields,
            }
        )
    return sections


def field_completion_entry(field: dict[str, Any], *, section_title: str | None = None) -> dict[str, Any]:
    return {
        "id": field["id"],
        "label": field["label"],
        "section_id": field["section_id"],
        "section_title": section_title or field.get("section_title", ""),
    }


def append_unique_field(
    items: list[dict[str, Any]],
    seen: set[str],
    field: dict[str, Any] | None,
    *,
    section_title: str | None = None,
) -> None:
    if not field or field["id"] in seen:
        return
    items.append(field_completion_entry(field, section_title=section_title))
    seen.add(field["id"])


def normalized_field_label(field: dict[str, Any]) -> str:
    return normalize_label(field.get("label", ""))


def field_requires_notes(field: dict[str, Any]) -> bool:
    return bool(field.get("notes_required")) and not field_is_basic_inputs(field)


def field_is_basic_inputs(field: dict[str, Any]) -> bool:
    return normalize_label(field.get("section_title", "")) == "basic inputs"


def field_requires_source_links(field: dict[str, Any]) -> bool:
    return not field_is_basic_inputs(field)


def section_title_contains(section: dict[str, Any], term: str) -> bool:
    return term in normalize_label(section.get("title", ""))


def find_field_by_labels(
    schema: dict[str, Any],
    labels: list[str],
    *,
    section: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized = {normalize_label(label) for label in labels}
    fields = section.get("fields", []) if section else schema.get("fields", [])
    return next((field for field in fields if normalized_field_label(field) in normalized), None)


def first_section_matching(schema: dict[str, Any], terms: list[str]) -> dict[str, Any] | None:
    normalized_terms = [normalize_label(term) for term in terms]
    for section in schema.get("sections", []):
        title = normalize_label(section.get("title", ""))
        if any(term in title for term in normalized_terms):
            return section
    return None


def decision_section(schema: dict[str, Any]) -> dict[str, Any] | None:
    for section in reversed(schema.get("sections", [])):
        if section_title_contains(section, "decision"):
            return section
    return None


def decision_field(schema: dict[str, Any]) -> dict[str, Any] | None:
    section = decision_section(schema)
    if section:
        field = find_field_by_labels(schema, ["Final Decision", "Decision"], section=section)
        if field:
            return field
    return find_field_by_labels(schema, ["Final Decision", "Decision"])


def review_date_field(schema: dict[str, Any]) -> dict[str, Any] | None:
    section = decision_section(schema)
    if section:
        for field in section.get("fields", []):
            label = normalized_field_label(field)
            if field.get("kind") == "date" or "review date" in label or "reassessment date" in label:
                return field
    return find_field_by_labels(schema, ["Review date, if Watchlist", "Recommended reassessment date"])


def override_rationale_field(schema: dict[str, Any]) -> dict[str, Any] | None:
    section = decision_section(schema)
    if section:
        field = find_field_by_labels(schema, ["Override rationale"], section=section)
        if field:
            return field
    return find_field_by_labels(schema, ["Override rationale"])


def override_rationale_is_strict_enough(text: str) -> bool:
    stripped = str(text or "").strip()
    if len(stripped) < STRICT_OVERRIDE_MIN_CHARS:
        return False
    return len(re.findall(r"\b[\w'-]+\b", stripped)) >= STRICT_OVERRIDE_MIN_WORDS


def hard_gate_result_category(value: str) -> str:
    normalized = normalize_label(value)
    if not normalized:
        return ""
    if any(term in normalized for term in ("archive", "stop")):
        return RESULT_ARCHIVE
    if any(
        term in normalized
        for term in (
            "watchlist",
            "needs verification",
            "needs smaller size",
            "buy small only",
            "hold existing",
            "return to underwriting",
            "trim review",
            "exit review",
        )
    ):
        return RESULT_WATCHLIST
    if any(term in normalized for term in ("pass", "clear", "continue", "approve", "proceed")):
        return RESULT_PROCEED
    return ""


def decision_severity(result: str) -> int:
    if result == RESULT_ARCHIVE:
        return 2
    if result in {
        RESULT_WATCHLIST,
        RESULT_RETURN_BUSINESS,
        RESULT_RETURN_MANAGEMENT,
        RESULT_RETURN_FINANCIAL,
        RESULT_RETURN_VALUATION,
    }:
        return 1
    if result == RESULT_PROCEED:
        return 0
    return -1


def hard_gate_summary_results(
    schema: dict[str, Any],
    responses: dict[str, Any],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    section = get_section(schema, "Hard Gate Summary") or first_section_matching(schema, ["hard gate summary"])
    if not section:
        return []

    rows: list[dict[str, Any]] = []
    for field in section.get("fields", []):
        label = str(field.get("label") or "")
        if " - " not in label or not label.endswith(" - Result"):
            continue
        row_name = label[: -len(" - Result")]
        value = field_value_from_stores(field, responses, metrics)
        rows.append(
            {
                "name": row_name,
                "field": field,
                "value": value,
                "category": hard_gate_result_category(value),
                "is_munger": "munger" in normalize_label(row_name),
            }
        )
    return rows


def decision_consistency_requirements(
    report: dict[str, Any],
    *,
    final_decision: str,
    normalized_decision: str,
    responses: dict[str, Any],
    metrics: dict[str, Any],
) -> list[str]:
    if not final_decision or not normalized_decision:
        return []

    schema = report.get("template", {}).get("schema", {})
    override_field = override_rationale_field(schema)
    override_text = field_value_from_stores(override_field, responses, metrics) if override_field else ""
    override_ready = override_rationale_is_strict_enough(override_text)
    resolved_review_date = str(report.get("review_date") or "").strip()
    if not resolved_review_date:
        review_field = review_date_field(schema)
        resolved_review_date = field_value_from_stores(review_field, responses, metrics) if review_field else ""
    requirements: list[str] = []

    final_severity = decision_severity(normalized_decision)
    overridden_gates = [
        row
        for row in hard_gate_summary_results(schema, responses, metrics)
        if not row["is_munger"] and decision_severity(row["category"]) > final_severity
    ]
    if overridden_gates and not override_ready:
        gate_summary = ", ".join(f"{row['name']} ({row['value']})" for row in overridden_gates if row["value"])
        if gate_summary:
            requirements.append(
                "Provide a strict override rationale before finalizing because the final decision is softer than: "
                f"{gate_summary}."
            )
        else:
            requirements.append(
                "Provide a strict override rationale before finalizing because the final decision overrides a non-pass hard gate."
            )

    if report.get("template", {}).get("stage_key") == "screening" and normalized_decision == RESULT_PROCEED:
        non_pass_gates = [
            row for row in hard_gate_summary_results(schema, responses, metrics) if not row["is_munger"] and row["category"] != RESULT_PROCEED
        ]
        if non_pass_gates and not override_ready:
            requirements.append(
                "Pass Screening requires every hard gate to be Pass unless Override rationale is filled with a strict case."
            )
        munger_row = next((row for row in hard_gate_summary_results(schema, responses, metrics) if row["is_munger"]), None)
        munger_field = find_field_by_labels(schema, ["Munger Check Result", "Munger checks - Result"])
        munger_value = str(munger_row.get("value") or "") if munger_row else ""
        if not munger_value and munger_field:
            munger_value = field_value_from_stores(munger_field, responses, metrics)
        if (munger_row or munger_field) and normalize_label(munger_value) != "clear" and not override_ready:
            requirements.append(
                "Pass Screening requires Munger checks to be Clear unless Override rationale is filled with a strict case."
            )

    if normalized_decision in {RESULT_WATCHLIST, RESULT_ARCHIVE} and not resolved_review_date:
        requirements.append(f"{normalized_decision} decisions require a review date.")

    if normalized_decision == RESULT_WATCHLIST and not normalize_objective_rules(report.get("watchlist_objective_rules") or []):
        requirements.append("Watchlist decisions require at least one objective monitoring rule.")

    if override_text and not override_ready:
        requirements.append(
            f"Override rationale must be specific and strict: at least {STRICT_OVERRIDE_MIN_WORDS} words and {STRICT_OVERRIDE_MIN_CHARS} characters."
        )
    return list(dict.fromkeys(requirements))


def watchlist_followup_section(schema: dict[str, Any]) -> dict[str, Any] | None:
    return (
        get_section(schema, "If It Goes To Watchlist")
        or get_section(schema, "If It Is Watchlisted")
        or first_section_matching(schema, ["watchlist"])
    )


def archive_followup_section(schema: dict[str, Any]) -> dict[str, Any] | None:
    return (
        get_section(schema, "If It Is Archived")
        or first_section_matching(schema, ["archived", "archive"])
    )


def pass_followup_section(schema: dict[str, Any]) -> dict[str, Any] | None:
    for title in (
        "If It Passes Screening",
        "If It Passes Business Underwriting",
        "If It Passes Management Underwriting",
        "If It Passes Financial Underwriting",
        "If It Is Approved For Execution",
    ):
        section = get_section(schema, title)
        if section:
            return section
    return first_section_matching(schema, ["if it passes", "if it pass"])


def return_followup_section(schema: dict[str, Any]) -> dict[str, Any] | None:
    return (
        get_section(schema, "If It Returns To Underwriting")
        or get_section(schema, "If It Is Returned To Underwriting")
        or first_section_matching(schema, ["returns to underwriting", "is returned", "returned to underwriting"])
    )


def decision_followup_section_for_choice(schema: dict[str, Any], final_decision: str) -> dict[str, Any] | None:
    normalized = normalize_label(final_decision)
    if not normalized:
        return None
    if "execute starter now" in normalized:
        return get_section(schema, "If It Executes Now")
    if "enter staged orders" in normalized:
        return get_section(schema, "If It Enters Staged Orders")
    if "hold existing" in normalized:
        return get_section(schema, "If It Holds Existing")
    if normalized == "trim" or normalized.startswith("trim "):
        return get_section(schema, "If It Is Trimmed Or Exited")
    if normalized == "exit" or normalized.startswith("exit "):
        return get_section(schema, "If It Is Trimmed Or Exited")
    if "watchlist" in normalized:
        return watchlist_followup_section(schema)
    if "archive" in normalized:
        return archive_followup_section(schema)
    if "return to underwriting" in normalized:
        return return_followup_section(schema)
    if "approve" in normalized or "pass" in normalized or "proceed" in normalized:
        return pass_followup_section(schema)
    return None


def summarize_filled_fields(fields: list[dict[str, Any]], responses: dict[str, Any], metrics: dict[str, Any]) -> str:
    parts = []
    for field in fields:
        value = field_value_from_stores(field, responses, metrics)
        if value:
            parts.append(f"{field['label']}: {value}")
    return "; ".join(parts)


def generic_report_summary_data(schema: dict[str, Any], responses: dict[str, Any], metrics: dict[str, Any]) -> dict[str, str]:
    summary_section = decision_section(schema)
    summary_field = find_field_by_labels(schema, ["Summary"], section=summary_section)
    explicit_summary = field_value_from_stores(summary_field, responses, metrics) if summary_field else ""
    if explicit_summary:
        latest_summary = explicit_summary
    else:
        summary_parts = []
        for label in ("Decision", "Final Decision", "Primary reason", "Main risk", "Main thing to verify"):
            field = find_field_by_labels(schema, [label], section=summary_section)
            value = field_value_from_stores(field, responses, metrics) if field else ""
            if value:
                pretty = "Decision" if label == "Final Decision" else label
                summary_parts.append(f"{pretty}: {value}")
        latest_summary = "; ".join(summary_parts)

    watchlist_field = find_field_by_labels(schema, ["Watchlist conditions"], section=summary_section)
    watchlist_conditions = field_value_from_stores(watchlist_field, responses, metrics) if watchlist_field else ""
    if not watchlist_conditions:
        watchlist_section = watchlist_followup_section(schema)
        if watchlist_section and watchlist_section is not summary_section:
            watchlist_conditions = summarize_filled_fields(watchlist_section.get("fields", []), responses, metrics)

    red_flags_field = find_field_by_labels(schema, ["Red flags", "Archive reason"], section=summary_section)
    archive_red_flags = field_value_from_stores(red_flags_field, responses, metrics) if red_flags_field else ""
    if not archive_red_flags:
        archive_section = archive_followup_section(schema)
        if archive_section and archive_section is not summary_section:
            archive_red_flags = summarize_filled_fields(archive_section.get("fields", []), responses, metrics)

    next_action = ""
    for label in (
        "Next action",
        "Action",
        "Immediate next checklist or memo",
        "Evidence needed before the next step",
        "Main missing input",
    ):
        field = find_field_by_labels(schema, [label], section=summary_section)
        if not field:
            field = find_field_by_labels(schema, [label])
        next_action = field_value_from_stores(field, responses, metrics) if field else ""
        if next_action:
            break

    review_field = review_date_field(schema)
    review_date = field_value_from_stores(review_field, responses, metrics) if review_field else ""

    return {
        "latest_summary": latest_summary,
        "watchlist_conditions": watchlist_conditions,
        "archive_red_flags": archive_red_flags,
        "next_action": next_action,
        "review_date": review_date,
    }


def generic_decision_mapping(schema: dict[str, Any]) -> dict[str, str]:
    mapping = {
        RESULT_PROCEED: RESULT_PROCEED,
        RESULT_WATCHLIST: RESULT_WATCHLIST,
        RESULT_ARCHIVE: RESULT_ARCHIVE,
    }
    field = decision_field(schema)
    for option in field.get("options", []) if field else []:
        normalized = screening_result_from_decision(option)
        if normalized:
            mapping[option] = normalized
    return mapping


def report_field_note_text(report: dict[str, Any], field_id: str) -> str:
    return str((report.get("field_notes") or {}).get(field_id) or "").strip()


def report_field_exception_status(report: dict[str, Any], field_id: str) -> str:
    return normalize_field_exception_status((report.get("field_exceptions") or {}).get(field_id))


def unique_sections(sections: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in sections:
        if not section:
            continue
        section_id = str(section.get("id") or "")
        if not section_id or section_id in seen:
            continue
        seen.add(section_id)
        items.append(section)
    return items


def alternate_outcome_sections(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return unique_sections(
        [
            pass_followup_section(schema),
            watchlist_followup_section(schema),
            archive_followup_section(schema),
            return_followup_section(schema),
            get_section(schema, "If It Executes Now"),
            get_section(schema, "If It Enters Staged Orders"),
            get_section(schema, "If It Holds Existing"),
            get_section(schema, "If It Is Trimmed Or Exited"),
            get_section(schema, "If It Is Approved For Execution"),
        ]
    )


def non_editable_field_ids(report: dict[str, Any]) -> set[str]:
    readonly = auto_inherited_field_ids(report)
    non_editable = set(readonly)
    for field in report.get("template", {}).get("schema", {}).get("fields", []):
        origin = str(field.get("origin") or "").strip().lower()
        if origin in {"derived", "system", "readonly", "read_only", "auto_inherited", "inherited"}:
            non_editable.add(field["id"])
    return non_editable


def decision_specific_field_is_exempt(
    field: dict[str, Any],
    *,
    normalized_decision: str,
) -> bool:
    label = normalized_field_label(field)
    if "watchlist" in label or "review date" in label or "reassessment date" in label:
        return normalized_decision != RESULT_WATCHLIST
    if label in {"red flags", "archive reason"}:
        return normalized_decision != RESULT_ARCHIVE
    return False


def exhaustive_completion_scope(
    report: dict[str, Any],
    responses: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    schema = report.get("template", {}).get("schema", {})
    decision = decision_field(schema)
    final_decision = field_value_from_stores(decision, responses, metrics) if decision else ""
    normalized_decision = screening_result_from_decision(final_decision, schema, responses, metrics)
    exempt_field_ids = non_editable_field_ids(report)

    selected_outcome_section = decision_followup_section_for_choice(schema, final_decision) if final_decision else None
    for section in alternate_outcome_sections(schema):
        if selected_outcome_section and section["id"] == selected_outcome_section["id"]:
            continue
        exempt_field_ids.update(field["id"] for field in section.get("fields", []))

    for field in schema.get("fields", []):
        if field["id"] in exempt_field_ids:
            continue
        if decision_specific_field_is_exempt(field, normalized_decision=normalized_decision):
            exempt_field_ids.add(field["id"])

    required_fields = [field for field in schema.get("fields", []) if field["id"] not in exempt_field_ids]
    return {
        "final_decision": final_decision,
        "normalized_decision": normalized_decision,
        "required_fields": required_fields,
        "exempt_field_ids": sorted(exempt_field_ids),
        "selected_outcome_section_id": str(selected_outcome_section["id"]) if selected_outcome_section else "",
    }


def exhaustive_completion_progress(
    schema: dict[str, Any],
    *,
    exempt_field_ids: set[str],
    covered_field_ids: set[str],
    answered_field_ids: set[str],
) -> list[dict[str, Any]]:
    progress: list[dict[str, Any]] = []
    for section in schema.get("sections", []):
        section_fields = section.get("fields", [])
        if not section_fields:
            continue
        required = [field for field in section_fields if field["id"] not in exempt_field_ids]
        progress.append(
            {
                "id": section["id"],
                "title": section["title"],
                "template_field_count": len(section_fields),
                "field_count": len(required),
                "exempt_field_count": len(section_fields) - len(required),
                "covered_field_count": sum(1 for field in required if field["id"] in covered_field_ids),
                "answered_field_count": sum(1 for field in required if field["id"] in answered_field_ids),
            }
        )
    return progress


def exhaustive_report_completion(report: dict[str, Any]) -> dict[str, Any]:
    schema = report.get("template", {}).get("schema", {})
    responses, metrics = merged_report_values(report)
    source_library = report.get("company_sources") or report.get("sources") or []
    source_map = {str(source["id"]): source for source in source_library}
    ready_sources = [source for source in source_library if source.get("normalized_status") == "ready"]
    scope = exhaustive_completion_scope(report, responses, metrics)
    required_fields = scope["required_fields"]
    exempt_field_ids = set(scope["exempt_field_ids"])
    final_decision = scope["final_decision"]
    normalized_decision = scope["normalized_decision"]

    missing_fields: list[dict[str, Any]] = []
    missing_source_links: list[dict[str, Any]] = []
    blocked_source_links: list[dict[str, Any]] = []
    missing_required_notes: list[dict[str, Any]] = []
    exception_missing_notes: list[dict[str, Any]] = []
    covered_field_ids: set[str] = set()
    answered_field_ids: set[str] = set()
    sourced_field_ids: set[str] = set()
    source_required_field_ids: set[str] = set()
    noted_field_ids: set[str] = set()
    required_note_field_ids: set[str] = set()
    required_noted_field_ids: set[str] = set()

    for field in required_fields:
        field_id = field["id"]
        value = raw_field_value_from_stores(field, responses, metrics)
        has_value = value not in (None, "")
        exception_status = "" if has_value else report_field_exception_status(report, field_id)
        if has_value:
            answered_field_ids.add(field_id)
            covered_field_ids.add(field_id)
        elif exception_status:
            covered_field_ids.add(field_id)
        else:
            missing_fields.append(field_completion_entry(field))
            continue

        if field_requires_source_links(field):
            source_required_field_ids.add(field_id)
            if report_field_has_sources(report, field):
                sourced_field_ids.add(field_id)
                linked_sources = report_field_sources(report, field, source_map)
                blocked = [
                    source
                    for source in linked_sources
                    if source.get("capture_state") in {SOURCE_CAPTURE_LINK_ONLY, SOURCE_CAPTURE_PENDING, SOURCE_CAPTURE_FAILED}
                ]
                if blocked:
                    blocked_source_links.append(
                        {
                            **field_completion_entry(field),
                            "blocked_source_ids": [int(source["id"]) for source in blocked],
                            "blocked_capture_states": [str(source.get("capture_state") or "") for source in blocked],
                        }
                    )
            else:
                missing_source_links.append(field_completion_entry(field))

        note_required = field_requires_notes(field) or bool(exception_status)
        if note_required:
            required_note_field_ids.add(field_id)

        if report_field_note_text(report, field_id):
            noted_field_ids.add(field_id)
            if note_required:
                required_noted_field_ids.add(field_id)
        elif exception_status:
            exception_missing_notes.append(field_completion_entry(field))
        elif note_required:
            missing_required_notes.append(field_completion_entry(field))

    decision_requirements: list[str] = []
    if not final_decision:
        decision_requirements.append("Choose a final decision before finalizing.")
    if "return to underwriting" in normalize_label(final_decision) and not normalized_decision:
        decision_requirements.append("Choose the underwriting stage this report should return to.")
    decision_requirements.extend(
        decision_consistency_requirements(
            report,
            final_decision=final_decision,
            normalized_decision=normalized_decision,
            responses=responses,
            metrics=metrics,
        )
    )

    field_count = len(required_fields)
    covered_count = len(covered_field_ids)
    answered_count = len(answered_field_ids)
    sourced_count = len(sourced_field_ids)
    source_required_count = len(source_required_field_ids)
    noted_count = len(noted_field_ids)
    required_note_count = len(required_note_field_ids)
    required_noted_count = len(required_noted_field_ids)

    warnings = completion_source_warnings(report, source_library)
    result_in_sync = True
    if final_decision and report.get("result") in REPORT_ACTIONS and screening_result_from_decision(
        final_decision, schema, responses, metrics
    ) != report["result"]:
        result_in_sync = False
        warnings.append("Top-level report result does not match the decision field.")

    complete_content = (
        not missing_fields
        and not missing_source_links
        and not blocked_source_links
        and not missing_required_notes
        and not exception_missing_notes
        and not decision_requirements
        and bool(final_decision)
    )
    legacy_incomplete_finalized = bool(report.get("result") and report["result"] != "Draft" and not complete_content)
    if legacy_incomplete_finalized:
        warnings.append("This saved report no longer meets the current exhaustive completion standard.")

    if complete_content and report.get("result") in REPORT_ACTIONS and result_in_sync:
        status = "complete"
    elif complete_content:
        status = "ready_to_finalize"
    elif covered_count or source_library or final_decision:
        status = "in_progress"
    else:
        status = "not_started"

    return {
        "status": status,
        "final_decision": final_decision,
        "decision_requirements": decision_requirements,
        "missing_fields": missing_fields,
        "missing_field_ids": [field["id"] for field in missing_fields],
        "missing_source_links": missing_source_links,
        "missing_source_field_ids": [field["id"] for field in missing_source_links],
        "blocked_source_links": blocked_source_links,
        "blocked_source_field_ids": [field["id"] for field in blocked_source_links],
        "missing_required_notes": missing_required_notes,
        "missing_required_note_ids": [field["id"] for field in missing_required_notes],
        "exception_missing_notes": exception_missing_notes,
        "exception_missing_note_ids": [field["id"] for field in exception_missing_notes],
        "answered_field_count": answered_count,
        "covered_field_count": covered_count,
        "sourced_field_count": sourced_count,
        "source_required_field_count": source_required_count,
        "noted_field_count": noted_count,
        "required_note_field_count": required_note_count,
        "required_noted_field_count": required_noted_count,
        "field_count": field_count,
        "template_field_count": len(schema.get("fields", [])),
        "exempt_field_count": len(exempt_field_ids),
        "exempt_field_ids": sorted(exempt_field_ids),
        "coverage_pct": round((covered_count / field_count) * 100, 2) if field_count else 100.0,
        "source_coverage_pct": round((sourced_count / source_required_count) * 100, 2) if source_required_count else 100.0,
        "notes_coverage_pct": round((required_noted_count / required_note_count) * 100, 2) if required_note_count else 100.0,
        "section_progress": exhaustive_completion_progress(
            schema,
            exempt_field_ids=exempt_field_ids,
            covered_field_ids=covered_field_ids,
            answered_field_ids=answered_field_ids,
        ),
        "source_count": len(source_library),
        "normalized_ready_source_count": len(ready_sources),
        "legacy_incomplete_finalized": legacy_incomplete_finalized,
        "warnings": warnings,
    }


def generic_report_completion(report: dict[str, Any]) -> dict[str, Any]:
    return exhaustive_report_completion(report)


def base_agent_contract(
    report: dict[str, Any],
    *,
    completion: dict[str, Any],
    guidance: list[str],
) -> dict[str, Any]:
    schema = report.get("template", {}).get("schema", {})
    response_field_ids = [field["id"] for field in schema.get("fields", []) if field.get("kind") not in {"metric", "number"}]
    metric_field_ids = [field["id"] for field in schema.get("fields", []) if field.get("kind") in {"metric", "number"}]
    workflow = report.get("workflow", {})
    readonly_field_ids = sorted(auto_inherited_field_ids(report))
    inherited_sources = inherited_report_sources(report)
    guidance_items = list(guidance)
    if readonly_field_ids:
        guidance_items.append(
            "Fields listed in inherited_fields are read-only handoff context. Do not write values to them, but you may still attach field_sources and field_notes."
        )
    if workflow.get("latest_previous_reports"):
        guidance_items.append(
            "Use workflow.latest_previous_reports as the canonical latest handoff chain from earlier stages. workflow.previous_reports keeps older completed history when you need extra context."
        )
    if decision_field(schema):
        guidance_items.append(
            "Watchlist and Archive decisions require a review_date. Watchlist decisions also require at least one watchlist_objective_rule; narrative watchlist triggers alone are not enough."
        )
    if report.get("suggested_sources"):
        guidance_items.append(
            "Prefer suggested_sources and report_source resources marked suggested_for_reuse before creating duplicate evidence records."
        )
    contract = {
        "version": 2,
        "report_kind": str(report.get("template", {}).get("stage_key") or ""),
        "goal": report.get("template", {}).get("description") or f"Complete the {report.get('stage_name', 'report')} report.",
        "guidance": guidance_items,
        "operations": {
            "preview_completion": {
                "method": "POST",
                "path": f"/api/reports/{report['id']}/preview",
                "content_type": "application/json",
                "expected_revision": int(report.get("revision") or 1),
                "behavior": "Runs the same synchronization and exhaustive completion logic as save/finalize, but does not persist changes.",
            },
            "save_report": {
                "method": "PATCH",
                "path": f"/api/reports/{report['id']}",
                "content_type": "application/json",
                "expected_revision": int(report.get("revision") or 1),
                "required_payload_fields": ["expected_revision"],
                "optional_payload_fields": ["finalize"],
                "allowed_response_field_ids": response_field_ids,
                "allowed_metric_field_ids": metric_field_ids,
                "allowed_field_exception_statuses": sorted(FIELD_EXCEPTION_STATUSES),
                "merge_patch": True,
                "conflict_behavior": "Returns 409 Conflict when expected_revision is stale.",
                "result_behavior": "Saving the decision field synchronizes the derived summary columns. Persisting a non-draft report.result now requires finalize=true.",
                "completion_behavior": "Returns 422 report_completion_blocked when finalize=true but exhaustive coverage, source coverage, required notes, exception notes, or decision requirements such as required review dates or watchlist monitoring rules are still missing.",
            },
            "save_source": {
                "method": "POST",
                "path": "/api/report-sources",
                "content_types": ["application/json", "multipart/form-data"],
                "json_file_fields": ["file_name", "file_content_base64", "file_mime_type"],
            },
            "update_source": {
                "method": "PATCH",
                "path_template": "/api/report-sources/{source_id}",
                "content_types": ["application/json", "multipart/form-data"],
                "json_file_fields": ["file_name", "file_content_base64", "file_mime_type"],
                "merge_patch": True,
            },
            "upload_document": {
                "method": "POST",
                "path": "/api/documents",
                "content_types": ["application/json", "multipart/form-data"],
                "json_file_fields": ["file_name", "file_content_base64", "file_mime_type"],
            },
        },
        "decision_mapping": generic_decision_mapping(schema),
        "fillable_sections": agent_fillable_sections(schema, readonly_field_ids=set(readonly_field_ids)),
        "field_exception_statuses": sorted(FIELD_EXCEPTION_STATUSES),
        "workflow": workflow,
        "suggested_sources": agent_suggested_sources(report),
        "resources": report_source_resources(report) + workflow_report_resources(report),
        "completion": completion,
    }
    if readonly_field_ids:
        contract["readonly_field_ids"] = readonly_field_ids
        contract["inherited_fields"] = {
            "field_ids": readonly_field_ids,
            "source_reports": inherited_sources,
            "behavior": "Values are refreshed from the latest completed upstream report and are not writable through save_report.",
            "annotations_allowed": True,
        }
    return contract


def underwriting_return_result(correct_stage: str) -> str:
    normalized = str(correct_stage or "").strip().lower()
    if "business" in normalized:
        return RESULT_RETURN_BUSINESS
    if "management" in normalized:
        return RESULT_RETURN_MANAGEMENT
    if "financial" in normalized:
        return RESULT_RETURN_FINANCIAL
    if "valuation" in normalized:
        return RESULT_RETURN_VALUATION
    return ""


def screening_result_from_decision(
    decision: str,
    schema: dict[str, Any] | None = None,
    responses: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> str:
    normalized = str(decision or "").strip().lower()
    if "return to business underwriting" in normalized:
        return RESULT_RETURN_BUSINESS
    if "return to management underwriting" in normalized:
        return RESULT_RETURN_MANAGEMENT
    if "return to financial underwriting" in normalized:
        return RESULT_RETURN_FINANCIAL
    if "return to valuation and position size" in normalized:
        return RESULT_RETURN_VALUATION
    if "return to underwriting" in normalized:
        correct_stage_field = find_field_by_labels(
            schema or {},
            ["Correct stage"],
            section=return_followup_section(schema or {}),
        )
        correct_stage = field_value_from_stores(correct_stage_field, responses or {}, metrics or {}) if correct_stage_field else ""
        return underwriting_return_result(correct_stage)
    if (
        "execute starter now" in normalized
        or "enter staged orders" in normalized
        or "hold existing" in normalized
        or normalized == "trim"
        or normalized.startswith("trim ")
        or normalized == "exit"
        or normalized.startswith("exit ")
    ):
        return RESULT_PROCEED
    if "approve" in normalized or "pass" in normalized or "proceed" in normalized:
        return RESULT_PROCEED
    if "watch" in normalized:
        return RESULT_WATCHLIST
    if "archive" in normalized:
        return RESULT_ARCHIVE
    return ""


def screening_decision_from_result(result: str) -> str:
    if result == RESULT_PROCEED:
        return "Pass Screening"
    if result == RESULT_WATCHLIST:
        return "Watchlist"
    if result == RESULT_ARCHIVE:
        return "Archive"
    if result == RESULT_RETURN_BUSINESS:
        return RESULT_RETURN_BUSINESS
    if result == RESULT_RETURN_MANAGEMENT:
        return RESULT_RETURN_MANAGEMENT
    if result == RESULT_RETURN_FINANCIAL:
        return RESULT_RETURN_FINANCIAL
    if result == RESULT_RETURN_VALUATION:
        return RESULT_RETURN_VALUATION
    return ""


def screening_section_value(
    schema: dict[str, Any], responses: dict[str, Any], metrics: dict[str, Any], section_title: str, field_label: str
) -> str:
    field = get_field(schema, field_label, section_title)
    if not field:
        return ""
    return field_value_from_stores(field, responses, metrics)


def screening_summary_data(schema: dict[str, Any], responses: dict[str, Any], metrics: dict[str, Any]) -> dict[str, str]:
    summary_parts = []
    for label in ("Decision", "Primary reason", "Main risk", "Main thing to verify"):
        value = screening_section_value(schema, responses, metrics, "Final Decision", label)
        if value:
            summary_parts.append(f"{label}: {value}")

    watchlist_section = get_section(schema, "If It Goes To Watchlist") or {"fields": []}
    watchlist_parts = []
    for field in watchlist_section.get("fields", []):
        value = field_value_from_stores(field, responses, metrics)
        if value:
            watchlist_parts.append(f"{field['label']}: {value}")

    archive_section = get_section(schema, "If It Is Archived") or {"fields": []}
    archive_parts = []
    for field in archive_section.get("fields", []):
        value = field_value_from_stores(field, responses, metrics)
        if value:
            archive_parts.append(f"{field['label']}: {value}")

    return {
        "latest_summary": "; ".join(summary_parts),
        "watchlist_conditions": "; ".join(watchlist_parts),
        "archive_red_flags": "; ".join(archive_parts),
        "next_action": screening_section_value(schema, responses, metrics, "One-Page Screening Conclusion", "Next action"),
        "review_date": screening_section_value(schema, responses, metrics, "Final Decision", "Review date, if Watchlist"),
    }


def synchronized_generic_payload(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    schema = report.get("template", {}).get("schema", {})
    merged_responses, merged_metrics = merged_report_values(report, payload)
    responses_payload = dict(payload["responses"]) if isinstance(payload.get("responses"), dict) else None

    # Keep the denormalized report columns in sync with schema fields so company
    # summaries and agents read a consistent state from the same payload.
    stage_key = report.get("template", {}).get("stage_key")
    stage_decision_field = decision_field(schema)
    if stage_decision_field and payload.get("result") in REPORT_ACTIONS and not merged_responses.get(stage_decision_field["id"]):
        responses_payload = responses_payload or {}
        responses_payload[stage_decision_field["id"]] = (
            screening_decision_from_result(payload["result"]) if stage_key == "screening" else payload["result"]
        )
        merged_responses[stage_decision_field["id"]] = responses_payload[stage_decision_field["id"]]

    stage_review_date = review_date_field(schema)
    if stage_review_date and payload.get("review_date") and not merged_responses.get(stage_review_date["id"]):
        responses_payload = responses_payload or {}
        responses_payload[stage_review_date["id"]] = payload["review_date"]
        merged_responses[stage_review_date["id"]] = payload["review_date"]

    if responses_payload is not None:
        payload["responses"] = responses_payload

    decision = field_value_from_stores(stage_decision_field, merged_responses, merged_metrics) if stage_decision_field else ""
    payload["result"] = (
        screening_result_from_decision(decision, schema, merged_responses, merged_metrics)
        or payload.get("result")
        or report.get("result")
        or "Draft"
    )
    summary_data = derive_report_summary(report.get("template", {}), merged_responses, merged_metrics)
    payload["summary"] = summary_data["latest_summary"] or payload.get("summary") or report.get("summary") or ""
    payload["watchlist_conditions"] = (
        summary_data["watchlist_conditions"] or payload.get("watchlist_conditions") or report.get("watchlist_conditions") or ""
    )
    payload["archive_red_flags"] = (
        summary_data["archive_red_flags"] or payload.get("archive_red_flags") or report.get("archive_red_flags") or ""
    )
    payload["next_action"] = summary_data["next_action"] or payload.get("next_action") or report.get("next_action") or ""
    payload["review_date"] = summary_data["review_date"] or payload.get("review_date") or report.get("review_date") or ""
    return payload


def synchronized_screening_payload(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    template = report.get("template") or {}
    if template.get("stage_key") != "screening":
        return payload

    payload = dict(payload)
    schema = template.get("schema", {})
    merged_responses, merged_metrics = merged_report_values(report, payload)
    responses_payload = dict(payload["responses"]) if isinstance(payload.get("responses"), dict) else None

    decision_field = get_section_field(schema, "Final Decision", "Decision")
    if decision_field and payload.get("result") in REPORT_ACTIONS and not merged_responses.get(decision_field["id"]):
        responses_payload = responses_payload or {}
        responses_payload[decision_field["id"]] = screening_decision_from_result(payload["result"])
        merged_responses[decision_field["id"]] = responses_payload[decision_field["id"]]

    review_date_field = get_section_field(schema, "Final Decision", "Review date, if Watchlist")
    if review_date_field and payload.get("review_date") and not merged_responses.get(review_date_field["id"]):
        responses_payload = responses_payload or {}
        responses_payload[review_date_field["id"]] = payload["review_date"]
        merged_responses[review_date_field["id"]] = payload["review_date"]

    if responses_payload is not None:
        payload["responses"] = responses_payload

    decision = screening_section_value(schema, merged_responses, merged_metrics, "Final Decision", "Decision")
    payload["result"] = screening_result_from_decision(decision) or payload.get("result") or "Draft"
    summary_data = screening_summary_data(schema, merged_responses, merged_metrics)
    payload["summary"] = summary_data["latest_summary"]
    payload["watchlist_conditions"] = summary_data["watchlist_conditions"]
    payload["archive_red_flags"] = summary_data["archive_red_flags"]
    payload["next_action"] = summary_data["next_action"]
    payload["review_date"] = summary_data["review_date"]
    return payload


def synchronized_report_payload(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if report.get("template", {}).get("stage_key") == "screening":
        return synchronized_screening_payload(report, payload)
    return synchronized_generic_payload(report, payload)


def screening_completion(report: dict[str, Any]) -> dict[str, Any]:
    return exhaustive_report_completion(report)


def screening_agent_contract(report: dict[str, Any]) -> dict[str, Any]:
    schema = report.get("template", {}).get("schema", {})
    completion = screening_completion(report)

    def section_fields(title: str) -> list[dict[str, Any]]:
        section = get_section(schema, title) or {"fields": []}
        return [agent_field_summary(field) for field in section.get("fields", [])]

    contract = base_agent_contract(
        report,
        completion=completion,
        guidance=[
            "Use field IDs from template.schema.field_lookup.by_id instead of relying on labels alone.",
            "Read prior completed workflow reports before answering later-stage prompts.",
            "Do not save a bare URL and stop there for website-only investor sources. Save the live URL plus a stored snapshot through /api/report-sources whenever the source may be cited later.",
            "Prefer text/html snapshots when page structure matters; prefer cleaned markdown or plain text when the visible text is already extracted; prefer CSV/XLSX for table-heavy investor data.",
            "Read normalized_url when available because it is the LLM-ready text view of the uploaded file.",
            "Cover every non-exempt editable field before finalizing. Non-selected outcome sections are exempt; everything else must be answered or explicitly excepted.",
            "Attach sources to every covered field. A field-level source link or a section-level source link both satisfy source coverage.",
            "Use field_exceptions only after investigation when a field cannot be answered cleanly. Every exception still requires a note and a source.",
            "Use field_notes for caveats, uncertainty, and audit trail. Notes are required for structured answers such as selects, dates, metrics, numbers, and structured datapoints; notes stay optional for narrative text fields unless an exception is used.",
            "Reuse existing company source IDs in later-stage field_sources instead of creating duplicate sources when the evidence already exists.",
            "All Screening question blocks, watchlist triggers, pass handoff items, and bias checklist items are explicit schema fields.",
            "Leave finalize=true for the last save, after the full report is covered and sourced.",
        ],
    )
    contract["goal"] = "Use normalized source evidence to complete the Screening report, make a final decision, and hand off cleanly to the next funnel state."
    contract["sections"] = {
        "final_decision": section_fields("Final Decision"),
        "pass_handoff": section_fields("If It Passes Screening"),
        "watchlist": section_fields("If It Goes To Watchlist"),
        "archive": section_fields("If It Is Archived"),
        "what_must_be_true": section_fields("Part VII. What Must Be True / What To Verify"),
        "one_page_conclusion": section_fields("One-Page Screening Conclusion"),
    }
    return contract


def data_collection_completion(report: dict[str, Any]) -> dict[str, Any]:
    completion = exhaustive_report_completion(report)
    schema = report.get("template", {}).get("schema", {})
    sections = {section["title"]: section for section in schema.get("sections", [])}
    coverage_rows: list[dict[str, Any]] = []
    coverage_section = sections.get("Required Source Coverage")
    if coverage_section:
        grouped: dict[str, dict[str, Any]] = {}
        suffixes = {
            " - Status": "status_field",
            " - Primary Source": "primary_source_field",
            " - Notes": "notes_field",
        }
        for field in coverage_section.get("fields", []):
            for suffix, key in suffixes.items():
                if field["label"].endswith(suffix):
                    row_label = field["label"][: -len(suffix)]
                    grouped.setdefault(row_label, {"source_type": row_label})[key] = field
                    break
        coverage_rows = list(grouped.values())

    missing_coverage_rows: list[str] = []
    for row in coverage_rows:
        status_field = row.get("status_field")
        primary_source_field = row.get("primary_source_field")
        if not status_field:
            continue
        status = field_value_from_report(report, status_field)
        if status not in {"Collected", "Alternative used"}:
            missing_coverage_rows.append(row["source_type"])
            continue

    ready_for_screening = (
        not completion["missing_fields"]
        and not missing_coverage_rows
        and bool(completion["source_count"])
        and bool(completion["normalized_ready_source_count"])
        and completion["final_decision"] == RESULT_PROCEED
        and report.get("result") == RESULT_PROCEED
        and not completion["warnings"]
    )
    return {
        **completion,
        "ready_for_screening": ready_for_screening,
        "missing_coverage_rows": missing_coverage_rows,
    }


def data_collection_agent_contract(report: dict[str, Any]) -> dict[str, Any]:
    schema = report.get("template", {}).get("schema", {})
    completion = data_collection_completion(report)
    coverage_section = get_section(schema, "Required Source Coverage") or {"fields": []}
    grouped_coverage: dict[str, dict[str, Any]] = {}
    for field in coverage_section.get("fields", []):
        if field["label"].endswith(" - Status"):
            row = field["label"][: -len(" - Status")]
            grouped_coverage.setdefault(row, {"source_type": row})["status_field_id"] = field["id"]
        elif field["label"].endswith(" - Primary Source"):
            row = field["label"][: -len(" - Primary Source")]
            grouped_coverage.setdefault(row, {"source_type": row})["primary_source_field_id"] = field["id"]
        elif field["label"].endswith(" - Notes"):
            row = field["label"][: -len(" - Notes")]
            grouped_coverage.setdefault(row, {"source_type": row})["notes_field_id"] = field["id"]

    def field_id(section_title: str, label: str) -> str:
        field = get_section_field(schema, section_title, label)
        return field["id"] if field else ""

    contract = base_agent_contract(
        report,
        completion=completion,
        guidance=[
            "Use field IDs from template.schema.field_lookup.by_id instead of relying on labels alone.",
            "Prefer /api/report-sources when a file should be cited inside the report. Use /api/documents for company-level uploads that are not yet report sources.",
            "Read normalized_url when available because it is the LLM-ready text view of the uploaded file.",
            "Cover every non-exempt editable field before finalizing. Source coverage is required for every covered field.",
            "Use field_exceptions only after investigation when a field cannot be answered. Exceptions require both a note and a source.",
            "Use field_notes for caveats and collection context. Notes are required for structured answers such as selects, dates, metrics, numbers, and structured datapoints; notes stay optional for narrative text fields unless an exception is used.",
            "Leave finalize=true for the last save, after the packet is fully covered and sourced.",
        ],
    )
    contract["goal"] = "Assemble a source pack, normalize it for LLM use, and hand off a complete packet to Screening."
    contract["sections"] = {
        "basic_inputs": {
            "company_field_id": field_id("Basic Inputs", "Company"),
            "ticker_field_id": field_id("Basic Inputs", "Ticker"),
            "date_field_id": field_id("Basic Inputs", "Date"),
            "analyst_field_id": field_id("Basic Inputs", "Analyst"),
            "primary_exchange_field_id": field_id("Basic Inputs", "Primary exchange"),
            "reporting_currency_field_id": field_id("Basic Inputs", "Reporting currency"),
        },
        "required_source_coverage": list(grouped_coverage.values()),
        "llm_ready_packet": {
            "read_first_field_id": field_id("LLM-Ready Packet", "What should Screening read first?"),
            "ignore_for_now_field_id": field_id("LLM-Ready Packet", "What should Screening ignore for now?"),
            "formatting_warnings_field_id": field_id(
                "LLM-Ready Packet", "What extraction warnings or formatting caveats matter most?"
            ),
            "top_questions_field_id": field_id(
                "LLM-Ready Packet", "What are the top three questions Screening should answer with this packet?"
            ),
            "result_field_id": field_id("LLM-Ready Packet", "Result"),
        },
        "screening_handoff": {
            "next_action_field_id": field_id("Screening Handoff", "Next action"),
            "main_missing_input_field_id": field_id("Screening Handoff", "Main missing input"),
            "verify_manually_field_id": field_id(
                "Screening Handoff", "Verify manually against original source"
            ),
            "revisit_if_better_sources_field_id": field_id(
                "Screening Handoff", "Revisit if better sources appear"
            ),
            "summary_field_id": field_id("Screening Handoff", "Summary"),
            "final_decision_field_id": field_id("Screening Handoff", "Final Decision"),
        },
    }
    return contract


def generic_stage_agent_contract(report: dict[str, Any]) -> dict[str, Any]:
    return base_agent_contract(
        report,
        completion=generic_report_completion(report),
        guidance=[
            "Use field IDs from template.schema.field_lookup.by_id instead of relying on labels alone.",
            "Read prior completed workflow reports before answering later-stage prompts.",
            "Do not save a bare URL and stop there for website-only investor sources. Save the live URL plus a stored snapshot through /api/report-sources whenever the source may be cited later.",
            "Prefer text/html snapshots when page structure matters; prefer cleaned markdown or plain text when the visible text is already extracted; prefer CSV/XLSX for table-heavy investor data.",
            "Read normalized_url when available because it is the LLM-ready text view of the uploaded file.",
            "Cover every non-exempt editable field before finalizing. Non-selected outcome sections are exempt; everything else must be answered or explicitly excepted.",
            "Attach sources to every covered field. A field-level source link or a section-level source link both satisfy source coverage.",
            "Use field_exceptions only after investigation when a field cannot be answered cleanly. Every exception still requires a note and a source.",
            "Use field_notes for caveats, uncertainty, and audit trail. Notes are required for structured answers such as selects, dates, metrics, numbers, and structured datapoints; notes stay optional for narrative text fields unless an exception is used.",
            "Reuse existing company source IDs in later-stage field_sources instead of creating duplicate sources when the evidence already exists.",
            "Leave finalize=true for the last save, after the full report is covered and sourced.",
        ],
    )


def build_agent_contract(report: dict[str, Any]) -> dict[str, Any] | None:
    template = report.get("template") or {}
    if template.get("stage_key") == "data_collection":
        return data_collection_agent_contract(report)
    if template.get("stage_key") == "screening":
        return screening_agent_contract(report)
    return generic_stage_agent_contract(report)


def workflow_reports(
    conn: sqlite3.Connection,
    company_id: int,
    *,
    before_stage_sequence: int | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [company_id]
    stage_filter = ""
    if before_stage_sequence is not None:
        stage_filter = "AND stages.sequence < ?"
        params.append(before_stage_sequence)
    rows = conn.execute(
        f"""
        SELECT reports.id, reports.stage_id, reports.template_id, reports.title, reports.report_month,
               reports.result, reports.summary, reports.next_action, reports.review_date, reports.updated_at,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence
        FROM reports
        JOIN stages ON stages.id = reports.stage_id
        WHERE reports.company_id = ?
          AND reports.result != 'Draft'
          {stage_filter}
        ORDER BY stages.sequence, reports.updated_at DESC, reports.id DESC
        """,
        params,
    ).fetchall()
    reports = []
    latest_stage_keys: set[str] = set()
    for row in rows:
        item = row_to_dict(row)
        stage_key = str(item.get("stage_key") or "")
        item["is_latest_for_stage"] = bool(stage_key) and stage_key not in latest_stage_keys
        if item["is_latest_for_stage"]:
            latest_stage_keys.add(stage_key)
        item["resource_uri"] = f"funnel://reports/{item['id']}"
        item["api_url"] = f"/api/reports/{item['id']}"
        reports.append(item)
    return reports


def latest_upstream_report(workflow: dict[str, Any]) -> dict[str, Any] | None:
    previous = list(workflow.get("latest_previous_reports") or workflow.get("previous_reports") or [])
    if not previous:
        return None
    highest_sequence = max(int(item.get("stage_sequence") or 0) for item in previous)
    candidates = [item for item in previous if int(item.get("stage_sequence") or 0) == highest_sequence]
    candidates.sort(key=lambda item: (str(item.get("updated_at") or ""), int(item.get("id") or 0)), reverse=True)
    return candidates[0] if candidates else None


def cited_source_ids_for_report(conn: sqlite3.Connection, report_id: int) -> set[str]:
    row = conn.execute("SELECT field_sources_json FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        return set()
    return linked_source_ids(load_json(row["field_sources_json"], {}))


def suggested_company_sources(conn: sqlite3.Connection, report: dict[str, Any]) -> list[dict[str, Any]]:
    company_sources = list(report.get("company_sources") or [])
    if not company_sources:
        return []

    current_ids = {str(source["id"]) for source in (report.get("sources") or [])}
    upstream = latest_upstream_report(report.get("workflow") or {})
    upstream_report_id = int(upstream["id"]) if upstream else 0
    cited_ids = cited_source_ids_for_report(conn, upstream_report_id) if upstream_report_id else set()
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
        suggested.append((suggested_source_sort_key(suggested_source, priority_bucket=bucket), suggested_source))
    suggested.sort(key=lambda item: item[0])
    return [source for _, source in suggested]


def latest_completed_report_for_stage(
    conn: sqlite3.Connection,
    company_id: int,
    stage_key: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT reports.id, reports.company_id, reports.stage_id, reports.template_id,
               reports.title, reports.report_month, reports.result, reports.summary,
               reports.next_action, reports.review_date, reports.updated_at, reports.created_at,
               reports.responses_json, reports.metrics_json,
               companies.ticker, companies.name AS company_name,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence,
               templates.name AS template_name, templates.description AS template_description,
               templates.markdown AS template_markdown, templates.schema_json AS template_schema_json
        FROM reports
        JOIN companies ON companies.id = reports.company_id
        JOIN stages ON stages.id = reports.stage_id
        JOIN templates ON templates.id = reports.template_id
        WHERE reports.company_id = ?
          AND stages.key = ?
          AND reports.result != 'Draft'
        ORDER BY reports.updated_at DESC, reports.id DESC
        LIMIT 1
        """,
        (company_id, stage_key),
    ).fetchone()
    if not row:
        return None
    return lightweight_report_context_item(row)


def report_section_value(report: dict[str, Any], section_title: str, field_label: str) -> str:
    schema = report.get("template", {}).get("schema", {})
    field = get_section_field(schema, section_title, field_label)
    return field_value_from_report(report, field) if field else ""


def first_nonempty(*values: str) -> str:
    for value in values:
        if str(value or "").strip():
            return str(value).strip()
    return ""


def screening_downstream_issues(screening_report: dict[str, Any]) -> str:
    explicit = report_section_value(
        screening_report,
        "One-Page Screening Conclusion",
        "Downstream issues to preserve",
    )
    if explicit:
        return explicit
    parts = []
    for label in (
        "Management Underwriting issue",
        "Financial Underwriting issue",
        "Valuation and Position Size issue",
        "Execution Rules issue",
    ):
        value = report_section_value(screening_report, "If It Passes Screening", label)
        if value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


def screening_evidence_review_summary(screening_report: dict[str, Any]) -> str:
    parts = []
    for label in (
        "Primary sources reviewed",
        "Competitor filings reviewed",
        "Other sources reviewed",
    ):
        value = report_section_value(screening_report, "Basic Inputs", label)
        if value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


def business_downstream_issues(business_report: dict[str, Any]) -> str:
    parts = []
    for label in (
        "Financial Underwriting issue",
        "Valuation and Position Size issue",
        "Execution Rules issue",
    ):
        value = report_section_value(business_report, "If It Passes Business Underwriting", label)
        if value:
            parts.append(f"{label}: {value}")
    for label in (
        "Main question for Financial Underwriting",
        "Main question for Valuation and Position Size",
    ):
        value = report_section_value(business_report, "Final Decision", label)
        if value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


def derive_business_underwriting_screening_handoff(
    conn: sqlite3.Connection,
    report: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    if report.get("stage_key") != "business_underwriting":
        return {}, None
    screening_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "screening")
    if not screening_report:
        return {}, None

    schema = report.get("template", {}).get("schema", {})
    inherited = get_section(schema, "Inherited From Screening") or {"fields": []}
    values_by_label = {
        "Company": first_nonempty(
            report_section_value(screening_report, "Basic Inputs", "Company"),
            screening_report.get("company_name", ""),
        ),
        "Ticker": first_nonempty(
            report_section_value(screening_report, "Basic Inputs", "Ticker"),
            screening_report.get("ticker", ""),
        ),
        "Date": report_section_value(screening_report, "Basic Inputs", "Date"),
        "Analyst": report_section_value(screening_report, "Basic Inputs", "Analyst"),
        "Fiscal year-end": report_section_value(screening_report, "Basic Inputs", "Fiscal year-end"),
        "Screening document reviewed": screening_report.get("title", ""),
        "Screening decision": first_nonempty(
            report_section_value(screening_report, "Final Decision", "Decision"),
            screening_report.get("result", ""),
        ),
        "Screening date": first_nonempty(
            report_section_value(screening_report, "One-Page Screening Conclusion", "Date"),
            report_section_value(screening_report, "Basic Inputs", "Date"),
        ),
        "Screening business category": first_nonempty(
            report_section_value(screening_report, "Final Decision", "Business category"),
            report_section_value(screening_report, "One-Page Screening Conclusion", "Category"),
        ),
        "Main business-quality claim that passed screening": first_nonempty(
            report_section_value(screening_report, "One-Page Screening Conclusion", "Why this might be interesting"),
            report_section_value(screening_report, "2. Why Is This Stock On The Desk?", "What is the simplest version of the potential thesis?"),
        ),
        "Main moat hypothesis inherited from screening": first_nonempty(
            report_section_value(screening_report, "One-Page Screening Conclusion", "Moat hypothesis"),
            report_section_value(screening_report, "Moat Hypothesis", "What is the moat? Do not name a moat type without evidence."),
        ),
        "Main business uncertainty left open by screening": first_nonempty(
            report_section_value(screening_report, "Final Decision", "Main thing to verify"),
            report_section_value(screening_report, "One-Page Screening Conclusion", "What must be true"),
            report_section_value(screening_report, "One-Page Screening Conclusion", "Main Business Underwriting task"),
        ),
        "Main business downside inherited from screening": first_nonempty(
            report_section_value(screening_report, "Final Decision", "Main risk"),
            report_section_value(screening_report, "One-Page Screening Conclusion", "Main disconfirming evidence"),
            report_section_value(screening_report, "One-Page Screening Conclusion", "Why this might be wrong"),
        ),
        "Main downstream issues already parked for later stages": screening_downstream_issues(screening_report),
        "External business evidence reviewed": screening_evidence_review_summary(screening_report),
    }

    responses: dict[str, str] = {}
    for field in inherited.get("fields", []):
        value = values_by_label.get(field["label"], "")
        if value:
            responses[field["id"]] = value

    return responses, {
        "report_id": int(screening_report["id"]),
        "title": screening_report.get("title", ""),
        "updated_at": screening_report.get("updated_at", ""),
        "result": screening_report.get("result", ""),
    }


def derive_management_underwriting_handoff(
    conn: sqlite3.Connection,
    report: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    if report.get("stage_key") != "management_underwriting":
        return {}, None

    business_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "business_underwriting")
    screening_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "screening")
    if not business_report and not screening_report:
        return {}, None

    schema = report.get("template", {}).get("schema", {})
    inherited = get_section(schema, "Inherited From Business Underwriting") or {"fields": []}
    handoff = get_section(schema, "Part I. Business Handoff And Delta Thesis") or {"fields": []}

    business_claim = first_nonempty(
        report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Screening claim tested"),
        report_section_value(business_report or {}, "Inherited From Screening", "Main business-quality claim that passed screening"),
        report_section_value(screening_report or {}, "One-Page Screening Conclusion", "Why this might be interesting"),
    )
    advantage = first_nonempty(
        report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Primary source of advantage"),
        report_section_value(business_report or {}, "Inherited From Screening", "Main moat hypothesis inherited from screening"),
    )
    fragility = first_nonempty(
        report_section_value(business_report or {}, "Final Decision", "Main business weakness"),
        report_section_value(business_report or {}, "Final Decision", "Main thing to verify"),
        report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Main disconfirming evidence"),
        report_section_value(screening_report or {}, "Final Decision", "Main risk"),
        report_section_value(screening_report or {}, "Final Decision", "Main thing to verify"),
    )
    management_question = first_nonempty(
        report_section_value(business_report or {}, "Final Decision", "Main question for Management Underwriting"),
        report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Main Management Underwriting task"),
        report_section_value(screening_report or {}, "If It Passes Screening", "Management Underwriting issue"),
    )
    downstream = first_nonempty(
        business_downstream_issues(business_report or {}),
        screening_downstream_issues(screening_report or {}),
    )

    values_by_label = {
        "Company": first_nonempty(
            report_section_value(business_report or {}, "Inherited From Screening", "Company"),
            report_section_value(screening_report or {}, "Basic Inputs", "Company"),
            report.get("company_name", ""),
        ),
        "Ticker": first_nonempty(
            report_section_value(business_report or {}, "Inherited From Screening", "Ticker"),
            report_section_value(screening_report or {}, "Basic Inputs", "Ticker"),
            report.get("ticker", ""),
        ),
        "Date": first_nonempty(
            report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Date"),
            report_section_value(business_report or {}, "Inherited From Screening", "Date"),
            report_section_value(screening_report or {}, "Basic Inputs", "Date"),
        ),
        "Analyst": first_nonempty(
            report_section_value(business_report or {}, "Inherited From Screening", "Analyst"),
            report_section_value(screening_report or {}, "Basic Inputs", "Analyst"),
        ),
        "Business Underwriting document reviewed": business_report.get("title", "") if business_report else "",
        "Business Underwriting decision": first_nonempty(
            report_section_value(business_report or {}, "Final Decision", "Decision"),
            business_report.get("result", "") if business_report else "",
        ),
        "Business Underwriting date": first_nonempty(
            report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Date"),
            report_section_value(business_report or {}, "Inherited From Screening", "Date"),
        ),
        "Business type from Business Underwriting": first_nonempty(
            report_section_value(business_report or {}, "Final Decision", "Business type"),
            report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Business type"),
            report_section_value(business_report or {}, "Inherited From Screening", "Screening business category"),
        ),
        "Main business claim proved": business_claim,
        "Source of competitive advantage already underwritten": advantage,
        "Unit-economics read inherited from Business Underwriting": report_section_value(
            business_report or {}, "One-Page Business Underwriting Conclusion", "Unit-economics read"
        ),
        "Capital-intensity read inherited from Business Underwriting": report_section_value(
            business_report or {}, "One-Page Business Underwriting Conclusion", "Economic-goodwill / capital-intensity read"
        ),
        "Main business fragility already identified": fragility,
        "Main question handed to Management Underwriting": management_question,
        "Main downstream issues already parked for later stages": downstream,
        "Other sources reviewed": first_nonempty(
            report_section_value(business_report or {}, "Inherited From Screening", "External business evidence reviewed"),
            screening_evidence_review_summary(screening_report or {}),
        ),
        "Which exact management claim from Business Underwriting is being tested now?": management_question,
        "What business facts are already considered proved and should not be re-underwritten here?": "; ".join(
            part for part in (
                f"Business claim: {business_claim}" if business_claim else "",
                f"Competitive advantage: {advantage}" if advantage else "",
                (
                    "Unit economics: "
                    + report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Unit-economics read")
                ) if report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Unit-economics read") else "",
                (
                    "Capital intensity: "
                    + report_section_value(
                        business_report or {},
                        "One-Page Business Underwriting Conclusion",
                        "Economic-goodwill / capital-intensity read",
                    )
                ) if report_section_value(
                    business_report or {},
                    "One-Page Business Underwriting Conclusion",
                    "Economic-goodwill / capital-intensity read",
                ) else "",
            ) if part
        ),
        "What would disprove continuation from Business Underwriting?": fragility,
        "Which questions are explicitly out of scope until Financial Underwriting, Valuation and Position Size, or Execution Rules?": downstream,
    }

    responses: dict[str, str] = {}
    for section in (inherited, handoff):
        for field in section.get("fields", []):
            value = values_by_label.get(field["label"], "")
            if value:
                responses[field["id"]] = value

    source_report = business_report or screening_report
    return responses, (
        {
            "report_id": int(source_report["id"]),
            "title": source_report.get("title", ""),
            "updated_at": source_report.get("updated_at", ""),
            "result": source_report.get("result", ""),
            "source_stage_key": source_report.get("stage_key", ""),
        }
        if source_report
        else None
    )


def management_downstream_issues(management_report: dict[str, Any]) -> str:
    parts = []
    for label in (
        "Financial Underwriting issue",
        "Valuation and Position Size issue",
        "Execution Rules issue",
    ):
        value = report_section_value(management_report, "If It Passes Management Underwriting", label)
        if value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


def derive_financial_underwriting_handoff(
    conn: sqlite3.Connection,
    report: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    if report.get("stage_key") != "financial_underwriting":
        return {}, None

    management_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "management_underwriting")
    business_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "business_underwriting")
    screening_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "screening")
    if not management_report and not business_report and not screening_report:
        return {}, None

    schema = report.get("template", {}).get("schema", {})
    inherited = get_section(schema, "Inherited From Management Underwriting") or {"fields": []}
    handoff = get_section(schema, "Part I. Management Handoff And Delta Thesis") or {"fields": []}

    business_type = first_nonempty(
        report_section_value(management_report or {}, "Inherited From Business Underwriting", "Business type from Business Underwriting"),
        report_section_value(business_report or {}, "Final Decision", "Business type"),
        report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Business type"),
    )
    core_business_model = first_nonempty(
        report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Why customers buy and stay"),
        report_section_value(screening_report or {}, "1. Business In Plain English", "What does the company do, in plain language?"),
        report_section_value(screening_report or {}, "1. Business In Plain English", "Can the business be explained without jargon?"),
    )
    unit_capital_read = "; ".join(
        part for part in (
            (
                "Unit economics: "
                + report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Unit-economics read")
            ) if report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Unit-economics read") else "",
            (
                "Capital intensity: "
                + report_section_value(
                    business_report or {},
                    "One-Page Business Underwriting Conclusion",
                    "Economic-goodwill / capital-intensity read",
                )
            ) if report_section_value(
                business_report or {},
                "One-Page Business Underwriting Conclusion",
                "Economic-goodwill / capital-intensity read",
            ) else "",
        ) if part
    )
    management_read = "; ".join(
        part for part in (
            (
                "Capital allocation: "
                + report_section_value(management_report or {}, "One-Page Management Conclusion", "Capital-allocation quick read")
            ) if report_section_value(management_report or {}, "One-Page Management Conclusion", "Capital-allocation quick read") else "",
            (
                "Incentives: "
                + report_section_value(management_report or {}, "One-Page Management Conclusion", "Incentive quick read")
            ) if report_section_value(management_report or {}, "One-Page Management Conclusion", "Incentive quick read") else "",
            (
                "Governance: "
                + report_section_value(management_report or {}, "One-Page Management Conclusion", "Governance or control quick read")
            ) if report_section_value(management_report or {}, "One-Page Management Conclusion", "Governance or control quick read") else "",
        ) if part
    )
    main_financial_question = first_nonempty(
        report_section_value(management_report or {}, "Final Decision", "Main Financial Underwriting task"),
        report_section_value(management_report or {}, "If It Passes Management Underwriting", "Financial Underwriting issue"),
        report_section_value(business_report or {}, "Final Decision", "Main question for Financial Underwriting"),
        report_section_value(business_report or {}, "If It Passes Business Underwriting", "Financial Underwriting issue"),
        report_section_value(screening_report or {}, "If It Passes Screening", "Financial Underwriting issue"),
    )
    downstream = first_nonempty(
        management_downstream_issues(management_report or {}),
        business_downstream_issues(business_report or {}),
        screening_downstream_issues(screening_report or {}),
    )
    financial_concern = first_nonempty(
        report_section_value(management_report or {}, "If It Passes Management Underwriting", "Financial Underwriting issue"),
        report_section_value(business_report or {}, "If It Passes Business Underwriting", "Financial Underwriting issue"),
        report_section_value(screening_report or {}, "If It Passes Screening", "Financial Underwriting issue"),
    )
    balance_sheet_risk = first_nonempty(
        report_section_value(screening_report or {}, "Final Decision", "Main risk"),
        report_section_value(business_report or {}, "Final Decision", "Main business weakness"),
        report_section_value(management_report or {}, "Final Decision", "Main risk"),
    )
    normalization_issue = first_nonempty(
        report_section_value(screening_report or {}, "If It Goes To Watchlist", "Valuation Uncertainty"),
        report_section_value(screening_report or {}, "Final Decision", "Main thing to verify"),
        report_section_value(business_report or {}, "Final Decision", "Main thing to verify"),
        financial_concern,
    )

    values_by_label = {
        "Company": first_nonempty(
            report_section_value(management_report or {}, "Inherited From Business Underwriting", "Company"),
            report_section_value(business_report or {}, "Inherited From Screening", "Company"),
            report_section_value(screening_report or {}, "Basic Inputs", "Company"),
            report.get("company_name", ""),
        ),
        "Ticker": first_nonempty(
            report_section_value(management_report or {}, "Inherited From Business Underwriting", "Ticker"),
            report_section_value(business_report or {}, "Inherited From Screening", "Ticker"),
            report_section_value(screening_report or {}, "Basic Inputs", "Ticker"),
            report.get("ticker", ""),
        ),
        "Date": first_nonempty(
            report_section_value(management_report or {}, "Inherited From Business Underwriting", "Date"),
            report_section_value(business_report or {}, "One-Page Business Underwriting Conclusion", "Date"),
            report_section_value(screening_report or {}, "Basic Inputs", "Date"),
        ),
        "Analyst": first_nonempty(
            report_section_value(management_report or {}, "Inherited From Business Underwriting", "Analyst"),
            report_section_value(screening_report or {}, "Basic Inputs", "Analyst"),
        ),
        "Management Underwriting document reviewed": management_report.get("title", "") if management_report else "",
        "Management Underwriting decision": first_nonempty(
            report_section_value(management_report or {}, "Final Decision", "Decision"),
            management_report.get("result", "") if management_report else "",
        ),
        "Management Underwriting date": first_nonempty(
            report_section_value(management_report or {}, "Inherited From Business Underwriting", "Date"),
            report_section_value(management_report or {}, "One-Page Management Conclusion", "Date"),
        ),
        "Business type inherited from Business Underwriting": business_type,
        "Core business model already underwritten": core_business_model,
        "Unit-economics and capital-intensity read inherited from Business Underwriting": unit_capital_read,
        "Capital-allocation, dilution, and governance read inherited from Management Underwriting": management_read,
        "Main financial question handed to this stage": main_financial_question,
        "Main accounting concern already identified": financial_concern,
        "Main balance-sheet risk already identified": balance_sheet_risk,
        "Main normalization issue already identified": normalization_issue,
        "Main downstream issues already parked for later stages": downstream,
        "Other sources reviewed": first_nonempty(
            report_section_value(management_report or {}, "Inherited From Business Underwriting", "Other sources reviewed"),
            report_section_value(business_report or {}, "Inherited From Screening", "External business evidence reviewed"),
            screening_evidence_review_summary(screening_report or {}),
        ),
        "Which exact financial claim from Screening, Business Underwriting, or Management Underwriting is being tested now?": main_financial_question,
        "What business and management facts are already considered proved and should not be re-underwritten here?": "; ".join(
            part for part in (
                f"Business type: {business_type}" if business_type else "",
                f"Business model: {core_business_model}" if core_business_model else "",
                unit_capital_read,
                management_read,
            ) if part
        ),
        "What would disprove continuation from Management Underwriting?": first_nonempty(
            report_section_value(management_report or {}, "Final Decision", "Main risk"),
            report_section_value(management_report or {}, "One-Page Management Conclusion", "Why this management might destroy value"),
            balance_sheet_risk,
        ),
        "Which questions are explicitly out of scope until Valuation and Position Size or Execution Rules?": downstream,
        "Which issues were deliberately parked for this stage by earlier work?": financial_concern,
    }

    responses: dict[str, str] = {}
    for section in (inherited, handoff):
        for field in section.get("fields", []):
            value = values_by_label.get(field["label"], "")
            if value:
                responses[field["id"]] = value

    source_report = management_report or business_report or screening_report
    return responses, (
        {
            "report_id": int(source_report["id"]),
            "title": source_report.get("title", ""),
            "updated_at": source_report.get("updated_at", ""),
            "result": source_report.get("result", ""),
            "source_stage_key": source_report.get("stage_key", ""),
        }
        if source_report
        else None
    )


def valuation_method_expectations(financial_pattern: str) -> tuple[str, str]:
    normalized = str(financial_pattern or "").strip().lower()
    if "financial" in normalized or "insurer" in normalized:
        return (
            "Book value / distributable earnings",
            "Capital adequacy / reserve / credit cross-check",
        )
    if "cyclical" in normalized or "commodity" in normalized or "asset-heavy" in normalized:
        return (
            "Normalized earnings power / asset value",
            "Cycle history / replacement-cost cross-check",
        )
    if "roll-up" in normalized:
        return (
            "Owner earnings / per-share value bridge",
            "Acquisition-adjusted cross-check",
        )
    if "asset-light" in normalized or "good predictable" in normalized:
        return (
            "Owner earnings / earning power",
            "No-rerating return / sensible comparables",
        )
    return "", ""


def derive_valuation_position_size_handoff(
    conn: sqlite3.Connection,
    report: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    if report.get("stage_key") != "valuation_position_size":
        return {}, None

    financial_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "financial_underwriting")
    if not financial_report:
        return {}, None

    schema = report.get("template", {}).get("schema", {})
    inherited = get_section(schema, "Inherited From Financial Underwriting") or {"fields": []}
    handoff = get_section(schema, "Part I. Financial Handoff And Valuation Delta Thesis") or {"fields": []}
    imported = get_section(schema, "1. Imported Economics From Financial Underwriting") or {"fields": []}

    financial_pattern = first_nonempty(
        report_section_value(financial_report, "Final Decision", "Financial pattern"),
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Financial pattern"),
        report_section_value(financial_report, "Fragile / Promotional / Over-Leveraged", "Financial Pattern Result"),
    )
    valuation_task = first_nonempty(
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Main Valuation and Position Size task"),
        report_section_value(financial_report, "If It Passes Financial Underwriting", "Business Underwriting handoff 1"),
        report_section_value(financial_report, "Final Decision", "Main thing to verify"),
    )
    execution_issue = first_nonempty(
        report_section_value(financial_report, "If It Passes Financial Underwriting", "Execution Rules issue"),
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Execution issue to preserve"),
    )
    low_owner_earnings = report_section_value(financial_report, "7. Normalization Bridge", "Low normalized owner earnings")
    base_owner_earnings = report_section_value(financial_report, "7. Normalization Bridge", "Base normalized owner earnings")
    high_owner_earnings = report_section_value(financial_report, "7. Normalization Bridge", "High normalized owner earnings")
    diluted_shares = first_nonempty(
        report_section_value(financial_report, "Basic Inputs", "Diluted shares"),
        report_section_value(financial_report, "6. Per-Share Value Creation And Retained-Capital Test", "Fully diluted share-count bridge"),
    )
    net_debt = report_section_value(financial_report, "Basic Inputs", "Net debt / net cash")
    current_price = report_section_value(financial_report, "Basic Inputs", "Current share price")
    current_market_cap = report_section_value(financial_report, "Basic Inputs", "Market capitalization")
    current_enterprise_value = report_section_value(financial_report, "Basic Inputs", "Enterprise value")
    normalized_maintenance_capex = report_section_value(financial_report, "7. Normalization Bridge", "Rough normalized maintenance capex")
    normalized_working_capital_need = report_section_value(financial_report, "7. Normalization Bridge", "Rough normalized working-capital need")
    normalized_tax_rate = report_section_value(financial_report, "7. Normalization Bridge", "Rough normalized tax rate")
    normalized_owner_earnings_per_share = first_nonempty(
        report_section_value(financial_report, "2. Owner Earnings Worksheet", "Owner earnings per share"),
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Owner earnings view"),
    )
    return_measure = first_nonempty(
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Returns on capital view"),
        report_section_value(financial_report, "3. Returns, Incremental Capital, And Margin Bridge", "Result"),
    )
    retained_capital_read = first_nonempty(
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Per-share value-creation view"),
        report_section_value(financial_report, "6. Per-Share Value Creation And Retained-Capital Test", "Result"),
    )
    buyback_and_dilution_read = first_nonempty(
        report_section_value(financial_report, "Inherited From Management Underwriting", "Capital-allocation, dilution, and governance read inherited from Management Underwriting"),
        retained_capital_read,
    )
    balance_sheet_read = first_nonempty(
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Balance sheet view"),
        report_section_value(financial_report, "5. Balance Sheet Stress Snapshot", "Result"),
    )
    permanent_loss_risk = report_section_value(financial_report, "Final Decision", "Main permanent-loss risk")
    safe_assume = first_nonempty(
        report_section_value(financial_report, "Final Decision", "What valuation can safely assume"),
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "What valuation can safely assume"),
    )
    must_not_assume = first_nonempty(
        report_section_value(financial_report, "Final Decision", "What valuation must not assume"),
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "What valuation must not assume"),
    )
    return_fact = first_nonempty(
        report_section_value(financial_report, "Final Decision", "Main thing to verify"),
        report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Main disconfirming evidence"),
        permanent_loss_risk,
    )
    expected_method, expected_cross_check = valuation_method_expectations(financial_pattern)
    imported_summary = "; ".join(
        part for part in (
            f"Business category: {financial_pattern}" if financial_pattern else "",
            f"Normalized owner earnings range: {low_owner_earnings} / {base_owner_earnings} / {high_owner_earnings}"
            if low_owner_earnings or base_owner_earnings or high_owner_earnings
            else "",
            f"Balance sheet: {balance_sheet_read}" if balance_sheet_read else "",
            f"Retained capital / dilution: {retained_capital_read}" if retained_capital_read else "",
            f"Safe assumptions: {safe_assume}" if safe_assume else "",
        )
        if part
    )

    values_by_label = {
        "Company": first_nonempty(
            report_section_value(financial_report, "Inherited From Management Underwriting", "Company"),
            report.get("company_name", ""),
        ),
        "Ticker": first_nonempty(
            report_section_value(financial_report, "Inherited From Management Underwriting", "Ticker"),
            report.get("ticker", ""),
        ),
        "Date": first_nonempty(
            report_section_value(financial_report, "Basic Inputs", "Date"),
            report_section_value(financial_report, "Inherited From Management Underwriting", "Date"),
        ),
        "Analyst": first_nonempty(
            report_section_value(financial_report, "Basic Inputs", "Analyst"),
            report_section_value(financial_report, "Inherited From Management Underwriting", "Analyst"),
        ),
        "Financial Underwriting document reviewed": financial_report.get("title", ""),
        "Financial Underwriting decision": first_nonempty(
            report_section_value(financial_report, "Final Decision", "Decision"),
            financial_report.get("result", ""),
        ),
        "Financial Underwriting date": first_nonempty(
            report_section_value(financial_report, "One-Page Financial Underwriting Conclusion", "Date"),
            report_section_value(financial_report, "Basic Inputs", "Date"),
        ),
        "Business category inherited": financial_pattern,
        "Main valuation question handed to this stage": valuation_task,
        "Main Execution Rules issue already parked for later": execution_issue,
        "Low normalized owner earnings inherited": low_owner_earnings,
        "Base normalized owner earnings inherited": base_owner_earnings,
        "High normalized owner earnings inherited": high_owner_earnings,
        "Diluted share count inherited": diluted_shares,
        "Net debt / net cash inherited": net_debt,
        "Enterprise value bridge inherited?": "Yes" if current_enterprise_value or net_debt or diluted_shares else "No",
        "Normalized maintenance capex inherited": normalized_maintenance_capex,
        "Normalized working-capital need inherited": normalized_working_capital_need,
        "Retained-capital read inherited": retained_capital_read,
        "Buyback / issuance / dilution read inherited": buyback_and_dilution_read,
        "Balance-sheet survivability read inherited": balance_sheet_read,
        "Main permanent-loss risk inherited": permanent_loss_risk,
        "What valuation can safely assume": safe_assume,
        "What valuation must not assume": must_not_assume,
        "Main fact that would force return to underwriting": return_fact,
        "Current share price": current_price,
        "Current market capitalization": current_market_cap,
        "Current enterprise value": current_enterprise_value,
        "Primary valuation method expected": expected_method,
        "Primary cross-check expected": expected_cross_check,
        "Worksheet or model used": report_section_value(financial_report, "Basic Inputs", "Financial model or worksheet used"),
        "Which exact valuation question from Financial Underwriting is being solved now?": valuation_task,
        "Which conclusions from earlier stages are being imported without rework?": imported_summary,
        "What single issue would force an immediate Return To Underwriting?": return_fact,
        "Which topics are explicitly out of scope until Execution Rules?": execution_issue,
        "Normalized owner earnings per share inherited": normalized_owner_earnings_per_share,
        "Normalized tax rate inherited": normalized_tax_rate,
        "Normalized return or spread measure inherited": return_measure,
        "Which imported figure matters most to the valuation?": first_nonempty(
            "Base normalized owner earnings" if base_owner_earnings else "",
            valuation_task,
        ),
        "Which imported figure is least reliable?": return_fact,
        "What would make the imported normalized range wrong?": first_nonempty(
            return_fact,
            must_not_assume,
            permanent_loss_risk,
        ),
    }

    responses: dict[str, str] = {}
    for section in (inherited, handoff, imported):
        for field in section.get("fields", []):
            value = values_by_label.get(field["label"], "")
            if value:
                responses[field["id"]] = value

    return responses, {
        "report_id": int(financial_report["id"]),
        "title": financial_report.get("title", ""),
        "updated_at": financial_report.get("updated_at", ""),
        "result": financial_report.get("result", ""),
        "source_stage_key": financial_report.get("stage_key", ""),
    }


def derive_execution_rules_handoff(
    conn: sqlite3.Connection,
    report: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    if report.get("stage_key") != "execution_rules":
        return {}, None

    valuation_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "valuation_position_size")
    if not valuation_report:
        return {}, None

    business_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "business_underwriting")
    management_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "management_underwriting")
    financial_report = latest_completed_report_for_stage(conn, int(report["company_id"]), "financial_underwriting")

    schema = report.get("template", {}).get("schema", {})
    part_one = get_section(schema, "Part I. Valuation Handoff And Execution Delta Thesis") or {"fields": []}
    master_snapshot = get_section(schema, "1. Master Snapshot Table") or {"fields": []}
    financial_snapshot = get_section(schema, "5. Financial Snapshot") or {"fields": []}
    valuation_snapshot = get_section(schema, "6. Valuation Snapshot") or {"fields": []}
    position_snapshot = get_section(schema, "7. Position, Portfolio, And Liquidity Snapshot") or {"fields": []}
    final_decision = get_section(schema, "Final Decision") or {"fields": []}

    company_name = first_nonempty(
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Company"),
        report.get("company_name", ""),
    )
    ticker = first_nonempty(
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Ticker"),
        report.get("ticker", ""),
    )
    valuation_date = first_nonempty(
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Date"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Date"),
    )
    analyst = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Analyst")
    valuation_decision = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Decision"),
        valuation_report.get("result", ""),
    )
    current_price = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Current price"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current share price"),
    )
    conservative_value = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Conservative worth per share"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Conservative worth per share"),
    )
    base_value = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Base worth per share"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Base worth per share"),
    )
    high_value = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "High worth per share"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "High worth per share"),
    )
    attractive_range = first_nonempty(
        report_section_value(valuation_report, "If It Is Approved For Execution", "Attractive / starter buy range"),
        report_section_value(valuation_report, "Final Decision", "Attractive price"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Attractive price"),
    )
    size_up_price = first_nonempty(
        report_section_value(valuation_report, "If It Is Approved For Execution", "Clearly cheap enough to size up"),
        report_section_value(valuation_report, "Final Decision", "Clearly cheap enough to size up"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Clearly cheap enough to size up"),
    )
    no_buy_above = first_nonempty(
        report_section_value(valuation_report, "If It Is Approved For Execution", "No-buy above"),
        report_section_value(valuation_report, "Final Decision", "Too expensive, even if the business is excellent"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Too expensive, even if the business is excellent"),
    )
    market_cap = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current market capitalization")
    enterprise_value = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current enterprise value")
    diluted_shares = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Diluted share count inherited")
    net_debt = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Net debt / net cash inherited")
    existing_position = first_nonempty(
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Existing position?"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current portfolio weight, if any"),
    )
    starter_size = first_nonempty(
        report_section_value(valuation_report, "If It Is Approved For Execution", "Starter size"),
        report_section_value(valuation_report, "Final Decision", "Proposed initial weight"),
    )
    full_size = report_section_value(valuation_report, "Final Decision", "Proposed full weight")
    hard_max = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Hard maximum weight"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Hard maximum weight"),
    )
    opportunity_cost = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Opportunity cost"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Opportunity cost"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current best alternative use of capital"),
    )
    main_verify = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Main thing to verify before buying"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Main thing to verify before buying"),
    )
    main_risk = first_nonempty(
        report_section_value(valuation_report, "Final Decision", "Main risk"),
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Why the stock might still fail"),
    )
    valuation_method = first_nonempty(
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Primary valuation method"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Primary valuation method expected"),
    )
    expected_return = report_section_value(
        valuation_report,
        "One-Page Valuation And Position Size Conclusion",
        "Expected return without rerating",
    )
    downside_view = first_nonempty(
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "Downside view"),
        main_risk,
    )
    safe_assume = first_nonempty(
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "What valuation can safely assume"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "What valuation can safely assume"),
    )
    must_not_assume = first_nonempty(
        report_section_value(valuation_report, "One-Page Valuation And Position Size Conclusion", "What valuation must not assume"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "What valuation must not assume"),
    )
    execution_issue = first_nonempty(
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Main Execution Rules issue already parked for later"),
        report_section_value(financial_report or {}, "One-Page Financial Underwriting Conclusion", "Execution issue to preserve"),
    )
    return_conditions = report_section_value(valuation_report, "If It Is Approved For Execution", "Return To Underwriting conditions")
    liquidity_notes = report_section_value(valuation_report, "If It Is Approved For Execution", "Liquidity / order-type considerations")
    best_alternative = first_nonempty(
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current best alternative use of capital"),
        opportunity_cost,
    )
    current_cash_level = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Current portfolio cash level")
    low_owner_earnings = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Low normalized owner earnings inherited")
    base_owner_earnings = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Base normalized owner earnings inherited")
    high_owner_earnings = report_section_value(valuation_report, "Inherited From Financial Underwriting", "High normalized owner earnings inherited")
    return_measure = report_section_value(valuation_report, "Inherited From Financial Underwriting", "Normalized return or spread measure inherited")
    balance_sheet_view = first_nonempty(
        report_section_value(financial_report or {}, "One-Page Financial Underwriting Conclusion", "Balance sheet view"),
        report_section_value(valuation_report, "Inherited From Financial Underwriting", "Balance-sheet survivability read inherited"),
    )
    dilution_view = report_section_value(
        valuation_report,
        "Inherited From Financial Underwriting",
        "Buyback / issuance / dilution read inherited",
    )
    normalization_view = first_nonempty(
        report_section_value(financial_report or {}, "One-Page Financial Underwriting Conclusion", "Normalization view"),
        main_verify,
    )
    accounting_reality = report_section_value(
        financial_report or {},
        "One-Page Financial Underwriting Conclusion",
        "Accounting reality",
    )

    def join_parts(*parts: str) -> str:
        return "; ".join(part for part in parts if part)

    imported_conclusions = join_parts(
        f"Decision: {valuation_decision}" if valuation_decision else "",
        f"Conservative / base / high worth: {conservative_value} / {base_value} / {high_value}"
        if conservative_value or base_value or high_value
        else "",
        f"Starter range: {attractive_range}" if attractive_range else "",
        f"Size-up price: {size_up_price}" if size_up_price else "",
        f"No-buy-above line: {no_buy_above}" if no_buy_above else "",
        f"Hard max: {hard_max}" if hard_max else "",
    )

    if "watchlist" in str(valuation_decision or "").lower():
        execution_problem = "Maintain a watchlist trigger and define the exact execution conditions before buying."
    elif existing_position:
        execution_problem = "Translate the valuation guardrails into concrete hold, add, trim, and exit rules for the existing position."
    else:
        execution_problem = "Translate the approved valuation range and sizing guardrails into exact first-entry execution rules."

    values_by_label = {
        "What exact execution problem is being solved now: first entry, add, hold, trim, exit, or re-open after new facts?": execution_problem,
        "Which stage-5 conclusions are imported without rework?": imported_conclusions,
        "What single fact would stop all buying immediately?": first_nonempty(main_verify, return_conditions, main_risk),
        "Which topics are explicitly out of scope unless new facts emerge?": first_nonempty(execution_issue, return_conditions),
        "Company - Value": company_name,
        "Ticker / exchange - Value": ticker,
        "Current share price - Value": current_price,
        "Diluted shares outstanding - Value": diluted_shares,
        "Market cap - Value": market_cap,
        "Net debt / net cash - Value": net_debt,
        "Enterprise value - Value": enterprise_value,
        "Existing position size - Value": existing_position,
        "Conservative worth per share - Value": conservative_value,
        "Base worth per share - Value": base_value,
        "High worth per share - Value": high_value,
        "Attractive / starter buy range - Value": attractive_range,
        "Clearly cheap enough to size up - Value": size_up_price,
        "No-buy-above line - Value": no_buy_above,
        "Proposed starter size - Value": starter_size,
        "Proposed full size - Value": full_size,
        "Hard max size - Value": hard_max,
        "Date of last Valuation and Position Size memo - Value": valuation_date,
        "Analyst / last updated - Value": analyst,
        "What is the best economics-tracking measure for this company: owner earnings, free cash flow, distributable earnings, underwriting earnings, or something else?": first_nonempty(
            report_section_value(financial_report or {}, "One-Page Financial Underwriting Conclusion", "Owner earnings view"),
            valuation_method,
        ),
        "What are low, base, and high owner-economics estimates?": join_parts(
            f"Low: {low_owner_earnings}" if low_owner_earnings else "",
            f"Base: {base_owner_earnings}" if base_owner_earnings else "",
            f"High: {high_owner_earnings}" if high_owner_earnings else "",
        ),
        "What is the return-on-capital read?": return_measure,
        "What is the cash-conversion read?": report_section_value(
            financial_report or {},
            "One-Page Financial Underwriting Conclusion",
            "Owner earnings view",
        ),
        "What does the balance-sheet position look like today?": balance_sheet_view,
        "How material are stock-based compensation, dilution, buybacks, or other share-count changes?": dilution_view,
        "What accounting judgment deserves the most skepticism?": accounting_reality,
        "What is the most important normalization judgment?": normalization_view,
        "What is the main balance-sheet or refinancing risk?": first_nonempty(
            report_section_value(financial_report or {}, "Final Decision", "Main permanent-loss risk"),
            main_risk,
        ),
        "What is the main financial strength?": first_nonempty(
            report_section_value(financial_report or {}, "Final Decision", "Main financial strength"),
            report_section_value(financial_report or {}, "One-Page Financial Underwriting Conclusion", "Why the financial record might be attractive"),
        ),
        "What primary valuation methods were used, and why do they fit the business?": valuation_method,
        "What is the conservative worth per share?": conservative_value,
        "What is the base worth per share?": base_value,
        "What is the high worth per share?": high_value,
        "What is the attractive or starter buy range?": attractive_range,
        "What price is clearly cheap enough to size up?": size_up_price,
        "What is the no-buy-above line?": no_buy_above,
        "What is the current price, and what discount or premium does it imply to conservative worth?": join_parts(
            f"Current price: {current_price}" if current_price else "",
            report_section_value(valuation_report, "Final Decision", "Discount / premium to conservative worth"),
        ),
        "What are the current market cap and enterprise value at the current quote?": join_parts(
            f"Market cap: {market_cap}" if market_cap else "",
            f"Enterprise value: {enterprise_value}" if enterprise_value else "",
        ),
        "What is the expected return without rerating?": expected_return,
        "What is the downside case?": downside_view,
        "What can valuation safely assume?": safe_assume,
        "What must valuation not assume?": must_not_assume,
        "What is the existing position size and cost basis, if any?": existing_position,
        "What are the proposed starter, full, and hard-max position sizes?": join_parts(
            f"Starter: {starter_size}" if starter_size else "",
            f"Full: {full_size}" if full_size else "",
            f"Hard max: {hard_max}" if hard_max else "",
        ),
        "How much cash or dry powder is actually available for this name?": current_cash_level,
        "What is the best alternative use of capital right now?": best_alternative,
        "What tax, account, mandate, or broker constraints matter?": liquidity_notes,
        "Which line should be used for execution, and why?": liquidity_notes,
        "What are average daily value and typical spread?": liquidity_notes,
        "Can the intended size be bought or sold in one normal session without distorting price materially?": liquidity_notes,
        "Current price": current_price,
        "Conservative worth per share": conservative_value,
        "Base worth per share": base_value,
        "High worth per share": high_value,
        "Attractive / starter buy range": attractive_range,
        "Clearly cheap enough to size up": size_up_price,
        "No-buy-above line": no_buy_above,
        "Existing weight": existing_position,
        "Hard max weight": hard_max,
        "Opportunity cost": opportunity_cost,
        "Main fact that would stop buying": first_nonempty(main_verify, return_conditions, main_risk),
    }

    for upstream_report, labels in (
        (
            business_report,
            {
                "What does the company actually sell?": ("One-Page Business Underwriting Conclusion", "Screening claim tested"),
                "Who pays, and which customer segment matters most?": ("One-Page Business Underwriting Conclusion", "Why customers buy and stay"),
                "What is the real market boundary being underwritten?": ("One-Page Business Underwriting Conclusion", "Market boundary"),
                "What moat mechanism matters most: cost, switching costs, network, brand, distribution, regulation, local scale, or something else?": ("One-Page Business Underwriting Conclusion", "Primary source of advantage"),
                "Which competitors or substitutes matter most?": ("One-Page Business Underwriting Conclusion", "Why competitors struggle"),
                "What is the current pricing-power read?": ("One-Page Business Underwriting Conclusion", "Pricing-power read"),
                "What is the reinvestment runway?": ("One-Page Business Underwriting Conclusion", "Reinvestment-runway read"),
                "What is the main capital-cycle, substitution, or disruption risk?": ("One-Page Business Underwriting Conclusion", "Capital-cycle read"),
                "What is the single biggest business downside?": ("Final Decision", "Main business weakness"),
                "What evidence most supports the business quality?": ("One-Page Business Underwriting Conclusion", "Core operating proof"),
            },
        ),
        (
            management_report,
            {
                "Who really controls capital allocation and culture?": ("One-Page Management Conclusion", "Who really runs capital allocation"),
                "What is the ownership and control structure?": ("One-Page Management Conclusion", "Governance or control quick read"),
                "What is the strongest evidence of integrity and candor?": ("One-Page Management Conclusion", "Candor quick read"),
                "What is the strongest evidence against trust or alignment?": ("One-Page Management Conclusion", "Why this management might destroy value"),
                "How has management treated outside owners in buybacks, issuance, leverage, and acquisitions?": ("One-Page Management Conclusion", "Capital-allocation quick read"),
                "What is the capital-allocation record in one paragraph?": ("One-Page Management Conclusion", "Capital-allocation quick read"),
                "What is the current incentive, governance, or agency concern?": ("One-Page Management Conclusion", "Incentive quick read"),
                "What is the succession and bench-strength read?": ("One-Page Management Conclusion", "Succession or depth quick read"),
                "What is the main management strength?": ("One-Page Management Conclusion", "Why this management might add value"),
                "What is the main management weakness?": ("One-Page Management Conclusion", "Main disconfirming evidence"),
            },
        ),
    ):
        if not upstream_report:
            continue
        for label, (section_title, field_label) in labels.items():
            values_by_label[label] = first_nonempty(values_by_label.get(label, ""), report_section_value(upstream_report, section_title, field_label))

    responses: dict[str, str] = {}
    for section in (
        part_one,
        master_snapshot,
        financial_snapshot,
        valuation_snapshot,
        position_snapshot,
        final_decision,
    ):
        for field in section.get("fields", []):
            value = values_by_label.get(field["label"], "")
            if value:
                responses[field["id"]] = value

    return responses, {
        "report_id": int(valuation_report["id"]),
        "title": valuation_report.get("title", ""),
        "updated_at": valuation_report.get("updated_at", ""),
        "result": valuation_report.get("result", ""),
        "source_stage_key": valuation_report.get("stage_key", ""),
    }


def auto_inherited_state(
    conn: sqlite3.Connection,
    report: dict[str, Any],
) -> tuple[
    dict[str, str],
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    auto_inherited_responses: dict[str, str] = {}
    inherited_screening = None
    inherited_business_underwriting = None
    inherited_management_underwriting = None
    inherited_financial_underwriting = None
    inherited_valuation_position_size = None

    stage_responses, inherited_screening = derive_business_underwriting_screening_handoff(conn, report)
    auto_inherited_responses.update(stage_responses)

    stage_responses, inherited_business_underwriting = derive_management_underwriting_handoff(conn, report)
    auto_inherited_responses.update(stage_responses)

    stage_responses, inherited_management_underwriting = derive_financial_underwriting_handoff(conn, report)
    auto_inherited_responses.update(stage_responses)

    stage_responses, inherited_financial_underwriting = derive_valuation_position_size_handoff(conn, report)
    auto_inherited_responses.update(stage_responses)

    stage_responses, inherited_valuation_position_size = derive_execution_rules_handoff(conn, report)
    auto_inherited_responses.update(stage_responses)

    return (
        auto_inherited_responses,
        inherited_screening,
        inherited_business_underwriting,
        inherited_management_underwriting,
        inherited_financial_underwriting,
        inherited_valuation_position_size,
    )


def report_workflow_context(conn: sqlite3.Connection, report: dict[str, Any]) -> dict[str, Any]:
    stage_row = conn.execute(
        "SELECT sequence, key, name FROM stages WHERE id = ?",
        (int(report["stage_id"]),),
    ).fetchone()
    next_stage = get_next_stage(conn, int(report["stage_id"]))
    previous_reports = workflow_reports(
        conn,
        int(report["company_id"]),
        before_stage_sequence=int(stage_row["sequence"]) if stage_row else None,
    )
    workflow = {
        "current_stage": {
            "id": int(report["stage_id"]),
            "key": stage_row["key"] if stage_row else "",
            "name": stage_row["name"] if stage_row else report.get("stage_name", ""),
            "sequence": int(stage_row["sequence"]) if stage_row else 0,
        },
        "next_stage": (
            {
                "id": int(next_stage["id"]),
                "key": next_stage["key"],
                "name": next_stage["name"],
                "sequence": int(next_stage["sequence"]),
            }
            if next_stage
            else None
        ),
        # Later stages need the completed handoff trail, not every draft ever created.
        "previous_reports": previous_reports,
    }
    workflow["latest_previous_reports"] = [item for item in previous_reports if item.get("is_latest_for_stage")]
    workflow["latest_upstream_report"] = latest_upstream_report(workflow)
    return workflow


def report_summary_item(
    row: sqlite3.Row,
    *,
    include_company: bool = False,
    include_completed_at: bool = False,
) -> dict[str, Any]:
    item = row_to_dict(row) or {}
    summary = {
        "id": int(item["id"]),
        "company_id": int(item["company_id"]),
        "title": item.get("title", ""),
        "report_month": item.get("report_month", ""),
        "result": item.get("result", ""),
        "summary": item.get("summary", ""),
        "next_action": item.get("next_action", ""),
        "review_date": item.get("review_date", ""),
        "stage_id": int(item["stage_id"]),
        "stage_key": item.get("stage_key", ""),
        "stage_name": item.get("stage_name", ""),
        "stage_sequence": int(item["stage_sequence"]),
        "updated_at": item.get("updated_at", ""),
        "created_at": item.get("created_at", ""),
    }
    if include_company:
        summary["ticker"] = item.get("ticker", "")
        summary["company_name"] = item.get("company_name", "")
    if include_completed_at:
        summary["completed_at"] = item.get("completed_at", "")
    return summary


def report_list_query_parts(
    *,
    company_id: int | None = None,
    stage_id: int | None = None,
    result: str | None = None,
    search: str | None = None,
    include_drafts: bool = True,
) -> tuple[str, list[Any]]:
    params: list[Any] = []
    clauses: list[str] = []
    if company_id is not None:
        clauses.append("reports.company_id = ?")
        params.append(company_id)
    if stage_id is not None:
        clauses.append("reports.stage_id = ?")
        params.append(stage_id)
    if result:
        clauses.append("reports.result = ?")
        params.append(result)
    if not include_drafts:
        clauses.append("reports.result != 'Draft'")
    if search:
        term = f"%{search}%"
        clauses.append(
            "(reports.title LIKE ? OR reports.summary LIKE ? OR reports.report_month LIKE ? OR companies.ticker LIKE ? OR companies.name LIKE ?)"
        )
        params.extend([term, term, term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def report_list_order_sql(order: str | None = None) -> str:
    mapping = {
        "completed_desc": "CASE WHEN COALESCE(reports.completed_at, '') = '' THEN 1 ELSE 0 END, reports.completed_at DESC, reports.id DESC",
        "completed_asc": "CASE WHEN COALESCE(reports.completed_at, '') = '' THEN 1 ELSE 0 END, reports.completed_at ASC, reports.id ASC",
        "updated_desc": "reports.updated_at DESC, reports.id DESC",
        "updated_asc": "reports.updated_at ASC, reports.id ASC",
        "company_asc": "companies.ticker ASC, companies.name ASC, reports.id DESC",
        "company_desc": "companies.ticker DESC, companies.name DESC, reports.id DESC",
        "stage_asc": "stages.sequence ASC, reports.completed_at DESC, reports.id DESC",
        "stage_desc": "stages.sequence DESC, reports.completed_at DESC, reports.id DESC",
        "result_asc": "reports.result ASC, reports.completed_at DESC, reports.id DESC",
        "result_desc": "reports.result DESC, reports.completed_at DESC, reports.id DESC",
        "title_asc": "reports.title ASC, reports.id DESC",
        "title_desc": "reports.title DESC, reports.id DESC",
    }
    return mapping.get(str(order or "updated_desc"), mapping["updated_desc"])


def count_reports(
    conn: sqlite3.Connection,
    company_id: int | None = None,
    *,
    stage_id: int | None = None,
    result: str | None = None,
    search: str | None = None,
    include_drafts: bool = True,
) -> int:
    where, params = report_list_query_parts(
        company_id=company_id,
        stage_id=stage_id,
        result=result,
        search=search,
        include_drafts=include_drafts,
    )
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM reports
        JOIN companies ON companies.id = reports.company_id
        JOIN stages ON stages.id = reports.stage_id
        {where}
        """,
        params,
    ).fetchone()
    return int(row["count"]) if row else 0


def list_report_summaries(
    conn: sqlite3.Connection,
    company_id: int | None = None,
    *,
    stage_id: int | None = None,
    result: str | None = None,
    search: str | None = None,
    include_drafts: bool = True,
    order: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    include_company: bool = False,
    include_completed_at: bool = False,
) -> list[dict[str, Any]]:
    where, params = report_list_query_parts(
        company_id=company_id,
        stage_id=stage_id,
        result=result,
        search=search,
        include_drafts=include_drafts,
    )
    order_sql = report_list_order_sql(order)
    limit_sql = ""
    limit_params: list[Any] = []
    if per_page is not None:
        safe_page = max(1, int(page or 1))
        safe_per_page = max(1, min(int(per_page or 500), 500))
        offset = (safe_page - 1) * safe_per_page
        limit_sql = "LIMIT ? OFFSET ?"
        limit_params = [safe_per_page, offset]
    rows = conn.execute(
        f"""
        SELECT reports.id, reports.company_id, reports.stage_id, reports.title, reports.report_month,
               reports.result, reports.summary, reports.next_action, reports.review_date,
               reports.updated_at, reports.created_at, reports.completed_at,
               companies.ticker, companies.name AS company_name,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence
        FROM reports
        JOIN companies ON companies.id = reports.company_id
        JOIN stages ON stages.id = reports.stage_id
        {where}
        ORDER BY {order_sql}
        {limit_sql}
        """,
        [*params, *limit_params],
    ).fetchall()
    return [
        report_summary_item(
            row,
            include_company=include_company,
            include_completed_at=include_completed_at,
        )
        for row in rows
    ]


def lightweight_report_context_item(row: sqlite3.Row | None) -> dict[str, Any] | None:
    item = row_to_dict(row)
    if not item:
        return None
    item["responses"] = load_json(item.pop("responses_json", None), {})
    item["metrics"] = load_json(item.pop("metrics_json", None), {})
    template = {
        "id": int(item["template_id"]),
        "stage_id": int(item["stage_id"]),
        "stage_name": item.get("stage_name", ""),
        "stage_key": item.get("stage_key", ""),
        "name": item.pop("template_name", ""),
        "description": item.pop("template_description", ""),
        "markdown": item.pop("template_markdown", None),
        "schema_json": item.pop("template_schema_json", None),
    }
    template["schema"] = stored_template_schema(template)
    template.pop("schema_json", None)
    template.pop("markdown", None)
    item["template"] = template
    return item


def get_lightweight_report_context(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT reports.id, reports.company_id, reports.stage_id, reports.template_id,
               reports.title, reports.report_month, reports.result, reports.summary,
               reports.next_action, reports.review_date, reports.updated_at, reports.created_at,
               reports.responses_json, reports.metrics_json,
               companies.ticker, companies.name AS company_name,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence,
               templates.name AS template_name, templates.description AS template_description,
               templates.markdown AS template_markdown, templates.schema_json AS template_schema_json
        FROM reports
        JOIN companies ON companies.id = reports.company_id
        JOIN stages ON stages.id = reports.stage_id
        JOIN templates ON templates.id = reports.template_id
        WHERE reports.id = ?
        """,
        (report_id,),
    ).fetchone()
    return lightweight_report_context_item(row)


def list_reports(conn: sqlite3.Connection, company_id: int | None = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if company_id:
        where = "WHERE reports.company_id = ?"
        params.append(company_id)
    rows = conn.execute(
        f"""
        SELECT reports.*, companies.ticker, companies.name AS company_name,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence,
               templates.name AS template_name
        FROM reports
        JOIN companies ON companies.id = reports.company_id
        JOIN stages ON stages.id = reports.stage_id
        JOIN templates ON templates.id = reports.template_id
        {where}
        ORDER BY reports.updated_at DESC, reports.id DESC
        """,
        params,
    ).fetchall()
    reports = []
    for row in rows:
        item = row_to_dict(row)
        for key in (
            "responses_json",
            "metrics_json",
            "section_ratings_json",
            "data_quality_json",
            "field_sources_json",
            "field_notes_json",
            "field_exceptions_json",
            "watchlist_objective_rules_json",
        ):
            parsed_name = key.replace("_json", "")
            item[parsed_name] = load_json(item.pop(key), [] if key.endswith("rules_json") else {})
        reports.append(item)
    return reports


def enriched_report_objective_rules(conn: sqlite3.Connection, report: dict[str, Any]) -> list[dict[str, Any]]:
    stored_rules = normalize_objective_rules(report.get("watchlist_objective_rules") or [])
    runtime_rows = conn.execute(
        """
        SELECT metric_name, comparator, threshold_value, unit, source, report_rule_key, current_value, notes
        FROM monitoring_rules
        WHERE report_id = ?
        ORDER BY id
        """,
        (int(report["id"]),),
    ).fetchall()
    runtime_by_rule_key = {
        monitoring_rule_report_key(row_to_dict(row) or {}): row_to_dict(row) or {}
        for row in runtime_rows
    }
    rules: list[dict[str, Any]] = []
    for rule in stored_rules:
        runtime = runtime_by_rule_key.get(rule["rule_key"], {})
        rules.append(
            {
                **rule,
                "current_value": runtime.get("current_value", rule.get("current_value")),
                "notes": runtime.get("notes", rule.get("notes", "")),
            }
        )
    return rules


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT reports.*, companies.ticker, companies.name AS company_name,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence,
               templates.name AS template_name
        FROM reports
        JOIN companies ON companies.id = reports.company_id
        JOIN stages ON stages.id = reports.stage_id
        JOIN templates ON templates.id = reports.template_id
        WHERE reports.id = ?
        """,
        (report_id,),
    ).fetchall()
    if not rows:
        return None
    item = row_to_dict(rows[0])
    for key in (
        "responses_json",
        "metrics_json",
        "section_ratings_json",
        "data_quality_json",
        "field_sources_json",
        "field_notes_json",
        "field_exceptions_json",
        "watchlist_objective_rules_json",
    ):
        parsed_name = key.replace("_json", "")
        item[parsed_name] = load_json(item.pop(key), [] if key.endswith("rules_json") else {})
    item["watchlist_objective_rules"] = enriched_report_objective_rules(conn, item)
    item["resource_uri"] = f"funnel://reports/{report_id}"
    item["api_url"] = f"/api/reports/{report_id}"
    item["template"] = get_template(conn, int(item["template_id"]))
    item["documents"] = list_documents(conn, int(item["company_id"]), report_id=report_id)
    item["sources"] = list_report_sources(conn, report_id)
    item["company_sources"] = list_company_sources(conn, int(item["company_id"]))
    item["workflow"] = report_workflow_context(conn, item)
    item["suggested_sources"] = suggested_company_sources(conn, item)
    item.update(normalize_report_state(item))
    (
        auto_inherited_responses,
        inherited_screening,
        inherited_business_underwriting,
        inherited_management_underwriting,
        inherited_financial_underwriting,
        inherited_valuation_position_size,
    ) = auto_inherited_state(conn, item)
    item["auto_inherited_fields"] = sorted(auto_inherited_responses)
    item["inherited_screening"] = inherited_screening
    item["inherited_business_underwriting"] = inherited_business_underwriting
    item["inherited_management_underwriting"] = inherited_management_underwriting
    item["inherited_financial_underwriting"] = inherited_financial_underwriting
    item["inherited_valuation_position_size"] = inherited_valuation_position_size
    for field_id, value in auto_inherited_responses.items():
        item["responses"][field_id] = value
    agent_contract = build_agent_contract(item)
    if agent_contract:
        item["agent_contract"] = agent_contract
        item["completion"] = agent_contract.get("completion", {})
    return item


def create_report(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    company_id = int(payload["company_id"])
    company = get_company_metadata(conn, company_id)
    if not company:
        raise KeyError("Company not found.")

    template_id = payload.get("template_id")
    template = get_template(conn, int(template_id)) if template_id else None
    if template_id and not template:
        raise ValueError("Template not found.")

    requested_stage_id = payload.get("stage_id")
    stage_id = int(requested_stage_id) if requested_stage_id not in (None, "") else None
    if template:
        template_stage_id = int(template["stage_id"])
        if stage_id is not None and template_stage_id != stage_id:
            raise ValueError("template_id must belong to the selected stage.")
        stage_id = template_stage_id
    else:
        stage_id = stage_id or company.get("current_stage_id") or first_stage_id(conn)
        if not stage_id:
            raise ValueError("At least one active stage is required before creating reports.")
        stage_id = int(stage_id)
        template = active_template_for_stage(conn, stage_id)
    if not template:
        raise ValueError("No active template exists for this stage.")

    report_month = payload.get("report_month") or datetime.now().strftime("%B %Y")
    stage_name = template.get("stage_name", "") if isinstance(template, dict) else ""
    if not stage_name:
        stage_row = conn.execute("SELECT name FROM stages WHERE id = ?", (stage_id,)).fetchone()
        stage_name = stage_row["name"] if stage_row else "Report"
    title = payload.get("title") or f"{stage_name} {report_month}"
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO reports
        (company_id, stage_id, template_id, title, report_month, revision, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (company_id, stage_id, int(template["id"]), title, report_month, timestamp, timestamp),
    )
    report_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    if company["bucket"] == "pool":
        conn.execute(
            "UPDATE companies SET bucket = 'funnel', current_stage_id = ?, updated_at = ? WHERE id = ?",
            (stage_id, timestamp, company_id),
        )

    # Persist stage handoff fields into the new draft so the UI and API read the
    # same initial state immediately instead of relying on transient computed values.
    created = get_lightweight_report_context(conn, report_id)
    if created:
        inherited_responses, _, _, _, _, _ = auto_inherited_state(conn, created)
        if inherited_responses:
            conn.execute(
                "UPDATE reports SET responses_json = ? WHERE id = ?",
                (dump_json(inherited_responses), report_id),
            )
    conn.commit()
    return get_report(conn, report_id)


def report_update_context(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    finalize_provided = "finalize" in payload
    finalize = parse_boolean_flag(payload.pop("finalize", False), field_name="finalize") if finalize_provided else False
    expected_revision_raw = payload.pop("expected_revision", report.get("revision"))
    try:
        expected_revision = int(expected_revision_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision must be an integer.") from exc
    current_revision = int(report.get("revision") or 1)
    if expected_revision != current_revision:
        raise ReportRevisionConflict(int(report["id"]), current_revision, str(report.get("updated_at") or ""))

    merged_payload = synchronized_report_payload(report, payload)
    merged_payload = merged_report_update_payload(report, merged_payload)
    desired_objective_rules = None
    if "watchlist_objective_rules" in merged_payload:
        desired_objective_rules = normalize_objective_rules(merged_payload["watchlist_objective_rules"])
    validate_report_update_payload(report, merged_payload)
    requested_result = str(merged_payload.get("result") or report.get("result") or "Draft")
    if not finalize_provided and requested_result in REPORT_ACTIONS and requested_result != str(report.get("result") or "Draft"):
        finalize = True
    enforce_completion_gate = finalize_provided and finalize
    persisted_result = requested_result if finalize else str(report.get("result") or "Draft")
    if not finalize and persisted_result not in {"Draft", *REPORT_ACTIONS}:
        persisted_result = "Draft"
    if enforce_completion_gate and requested_result not in REPORT_ACTIONS:
        raise ValueError("Choose a final decision before finalizing.")

    completion_payload = dict(merged_payload)
    if desired_objective_rules is not None:
        completion_payload["watchlist_objective_rules"] = desired_objective_rules
    completion_candidate = report_state_with_payload(
        report,
        completion_payload,
        persisted_result=persisted_result if not finalize else requested_result,
    )
    completion = exhaustive_report_completion(completion_candidate)
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


def preview_report_completion(conn: sqlite3.Connection, report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    report = get_report(conn, report_id)
    if not report:
        raise KeyError("Report not found.")
    context = report_update_context(report, payload)
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


def update_report(conn: sqlite3.Connection, report_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    report = get_report(conn, report_id)
    if not report:
        raise KeyError("Report not found.")
    context = report_update_context(report, payload)
    desired_objective_rules = context["desired_objective_rules"]
    write_payload = dict(context["payload"])
    write_payload.pop("completed_at", None)
    if context["enforce_completion_gate"] and context["completion"]["status"] != "complete":
        raise ReportCompletionBlocked(context["completion"])

    if desired_objective_rules is not None:
        write_payload["watchlist_objective_rules"] = stored_objective_rules(desired_objective_rules)
    write_payload["result"] = context["persisted_result"]
    timestamp = now_iso()
    if context["finalize"] and context["requested_result"] in REPORT_ACTIONS:
        write_payload["completed_at"] = timestamp
    fields = []
    values: list[Any] = []
    direct_fields = (
        "title",
        "report_month",
        "result",
        "summary",
        "watchlist_conditions",
        "watchlist_subjective_rules",
        "archive_red_flags",
        "next_action",
        "review_date",
    )
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
    for key in direct_fields:
        if key in write_payload:
            fields.append(f"{key} = ?")
            values.append(write_payload.get(key) or "")
    for source_key, column in json_fields.items():
        if source_key in write_payload:
            fields.append(f"{column} = ?")
            values.append(dump_json(write_payload.get(source_key)))
    if "completed_at" in write_payload:
        fields.append("completed_at = ?")
        values.append(write_payload.get("completed_at") or "")
    if fields:
        fields.append("revision = ?")
        values.append(int(report.get("revision") or 1) + 1)
        fields.append("updated_at = ?")
        values.append(timestamp)
        values.extend([report_id, context["expected_revision"]])
        cursor = conn.execute(
            f"UPDATE reports SET {', '.join(fields)} WHERE id = ? AND revision = ?",
            values,
        )
        if cursor.rowcount == 0:
            current = conn.execute("SELECT revision, updated_at FROM reports WHERE id = ?", (report_id,)).fetchone()
            if not current:
                raise KeyError("Report not found.")
            raise ReportRevisionConflict(report_id, int(current["revision"]), str(current["updated_at"] or ""))
    if context["finalize"] and context["requested_result"] in REPORT_ACTIONS:
        apply_report_result(conn, report_id, write_payload["result"])
    conn.commit()
    create_monitoring_rules_from_report(
        conn,
        {
            "id": report_id,
            "company_id": int(report["company_id"]),
            "result": write_payload.get("result", report.get("result", "")),
            "watchlist_objective_rules": (
                desired_objective_rules
                if desired_objective_rules is not None
                else report.get("watchlist_objective_rules") or []
            ),
        },
        desired_rules=desired_objective_rules,
    )
    return get_report(conn, report_id)


def apply_report_result(conn: sqlite3.Connection, report_id: int, result: str) -> None:
    report = conn.execute(
        "SELECT company_id, stage_id FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    if not report:
        return
    company_id = int(report["company_id"])
    stage_id = int(report["stage_id"])
    if result == RESULT_PROCEED:
        next_stage = get_next_stage(conn, stage_id)
        if next_stage:
            set_company_position(conn, company_id, "funnel", int(next_stage["id"]))
        else:
            set_company_position(conn, company_id, "monitoring", None)
    elif result == RESULT_WATCHLIST:
        set_company_position(conn, company_id, "watchlist", None)
    elif result == RESULT_ARCHIVE:
        set_company_position(conn, company_id, "archive", None)
    elif return_stage_key_from_result(result):
        set_company_position(conn, company_id, "funnel", stage_id_by_key(conn, return_stage_key_from_result(result) or ""))


def set_company_position(
    conn: sqlite3.Connection,
    company_id: int,
    bucket: str,
    current_stage_id: int | None,
) -> None:
    conn.execute(
        """
        UPDATE companies
        SET bucket = ?, current_stage_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (bucket, current_stage_id, now_iso(), company_id),
    )


def stage_id_by_key(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute("SELECT id FROM stages WHERE key = ?", (key,)).fetchone()
    return int(row["id"]) if row else None


def return_stage_key_from_result(result: str) -> str | None:
    normalized = str(result or "").strip().lower()
    if normalized == RESULT_RETURN_BUSINESS.lower():
        return "business_underwriting"
    if normalized == RESULT_RETURN_MANAGEMENT.lower():
        return "management_underwriting"
    if normalized == RESULT_RETURN_FINANCIAL.lower():
        return "financial_underwriting"
    if normalized == RESULT_RETURN_VALUATION.lower():
        return "valuation_position_size"
    return None


def reconcile_company_position(conn: sqlite3.Connection, company_id: int) -> None:
    latest_completed = conn.execute(
        """
        SELECT stage_id, result
        FROM reports
        WHERE company_id = ? AND result != 'Draft'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (company_id,),
    ).fetchone()
    if latest_completed:
        stage_id = int(latest_completed["stage_id"])
        result = latest_completed["result"]
        if result == RESULT_PROCEED:
            next_stage = get_next_stage(conn, stage_id)
            if next_stage:
                set_company_position(conn, company_id, "funnel", int(next_stage["id"]))
            else:
                set_company_position(conn, company_id, "monitoring", None)
        elif result == RESULT_WATCHLIST:
            set_company_position(conn, company_id, "watchlist", None)
        elif result == RESULT_ARCHIVE:
            set_company_position(conn, company_id, "archive", None)
        elif return_stage_key_from_result(result):
            set_company_position(conn, company_id, "funnel", stage_id_by_key(conn, return_stage_key_from_result(result) or ""))
        return

    latest_draft = conn.execute(
        """
        SELECT stage_id
        FROM reports
        WHERE company_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (company_id,),
    ).fetchone()
    if latest_draft:
        set_company_position(conn, company_id, "funnel", int(latest_draft["stage_id"]))
    else:
        set_company_position(conn, company_id, "pool", None)


def delete_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any]:
    report = conn.execute(
        "SELECT company_id FROM reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not report:
        raise KeyError("Report not found.")
    company_id = int(report["company_id"])
    conn.execute("DELETE FROM monitoring_rules WHERE report_id = ?", (report_id,))
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    reconcile_company_position(conn, company_id)
    conn.commit()
    company = get_company(conn, company_id)
    if not company:
        raise KeyError("Company not found.")
    return company


def list_documents(
    conn: sqlite3.Connection, company_id: int, report_id: int | None = None
) -> list[dict[str, Any]]:
    params: list[Any] = [company_id]
    where = "WHERE company_id = ?"
    if report_id:
        where += " AND report_id = ?"
        params.append(report_id)
    rows = conn.execute(
        f"SELECT * FROM documents {where} ORDER BY uploaded_at DESC, id DESC", params
    ).fetchall()
    return [decorate_document_record(row_to_dict(row)) for row in rows if row]


def list_company_sources(conn: sqlite3.Connection, company_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT report_sources.*, reports.title AS report_title, reports.result AS report_result,
               stages.name AS stage_name, stages.key AS stage_key, stages.sequence AS stage_sequence,
               documents.original_name AS document_name,
               documents.mime_type AS document_mime_type, documents.normalized_status,
               documents.normalized_format, documents.normalized_method, documents.normalized_notes,
               documents.normalized_preview, documents.normalized_text_path
        FROM report_sources
        JOIN reports ON reports.id = report_sources.report_id
        JOIN stages ON stages.id = reports.stage_id
        LEFT JOIN documents ON documents.id = report_sources.document_id
        WHERE reports.company_id = ?
        ORDER BY reports.updated_at DESC, report_sources.updated_at DESC, report_sources.id DESC
        """,
        (company_id,),
    ).fetchall()
    sources = []
    for row in rows:
        item = row_to_dict(row)
        item["tags"] = load_json(item.pop("tags_json"), [])
        decorate_source_record(item)
        sources.append(item)
    return sources


def sanitize_filename(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "._- ")
    cleaned = cleaned.strip().replace(" ", "_")
    return cleaned or "upload.bin"


def cleanup_written_paths(paths: list[Path]) -> None:
    for path in reversed(paths):
        with suppress(FileNotFoundError):
            path.unlink()


def background_job_health(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = {
        JOB_STATUS_PENDING: 0,
        JOB_STATUS_RUNNING: 0,
        JOB_STATUS_COMPLETED: 0,
        JOB_STATUS_FAILED: 0,
    }
    for row in conn.execute(
        "SELECT status, COUNT(*) AS count FROM background_jobs GROUP BY status"
    ).fetchall():
        counts[str(row["status"] or JOB_STATUS_PENDING)] = int(row["count"] or 0)
    return {
        "pending_jobs": counts.get(JOB_STATUS_PENDING, 0),
        "running_jobs": counts.get(JOB_STATUS_RUNNING, 0),
        "completed_jobs": counts.get(JOB_STATUS_COMPLETED, 0),
        "failed_jobs": counts.get(JOB_STATUS_FAILED, 0),
    }


def enqueue_document_normalization_job(conn: sqlite3.Connection, document_id: int) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO background_jobs
        (kind, document_id, payload_json, status, attempt_count, max_attempts, leased_by, leased_at,
         available_at, last_error, completed_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, 0, ?, '', '', ?, '', '', ?, ?)
        ON CONFLICT(kind, document_id) DO UPDATE SET
            status = excluded.status,
            leased_by = '',
            leased_at = '',
            available_at = excluded.available_at,
            last_error = '',
            completed_at = '',
            updated_at = excluded.updated_at
        """,
        (
            JOB_KIND_DOCUMENT_NORMALIZATION,
            document_id,
            dump_json({"document_id": document_id}),
            JOB_STATUS_PENDING,
            MAX_JOB_ATTEMPTS,
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def lease_background_job(
    conn: sqlite3.Connection,
    worker_id: str,
    *,
    lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
) -> dict[str, Any] | None:
    lease_cutoff = datetime.now(UTC).timestamp() - lease_seconds
    row = conn.execute(
        """
        SELECT id, kind, document_id, payload_json, attempt_count, max_attempts
        FROM background_jobs
        WHERE status = ?
          AND (available_at = '' OR available_at <= ?)
        ORDER BY available_at, id
        LIMIT 1
        """,
        (JOB_STATUS_PENDING, now_iso()),
    ).fetchone()
    if not row:
        row = conn.execute(
            """
            SELECT id, kind, document_id, payload_json, attempt_count, max_attempts
            FROM background_jobs
            WHERE status = ?
              AND leased_at != ''
              AND strftime('%s', leased_at) <= ?
            ORDER BY leased_at, id
            LIMIT 1
            """,
            (JOB_STATUS_RUNNING, str(int(lease_cutoff))),
        ).fetchone()
    if not row:
        return None
    item = row_to_dict(row)
    if not item:
        return None
    timestamp = now_iso()
    cursor = conn.execute(
        """
        UPDATE background_jobs
        SET status = ?, attempt_count = attempt_count + 1, leased_by = ?, leased_at = ?, updated_at = ?
        WHERE id = ?
          AND status IN (?, ?)
        """,
        (
            JOB_STATUS_RUNNING,
            worker_id,
            timestamp,
            timestamp,
            int(item["id"]),
            JOB_STATUS_PENDING,
            JOB_STATUS_RUNNING,
        ),
    )
    if cursor.rowcount == 0:
        return None
    leased = conn.execute("SELECT * FROM background_jobs WHERE id = ?", (int(item["id"]),)).fetchone()
    return row_to_dict(leased)


def complete_background_job(conn: sqlite3.Connection, job_id: int) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        UPDATE background_jobs
        SET status = ?, leased_by = '', leased_at = '', last_error = '', completed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (JOB_STATUS_COMPLETED, timestamp, timestamp, job_id),
    )


def fail_background_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    attempt_count: int,
    max_attempts: int,
    message: str,
) -> None:
    timestamp = now_iso()
    if attempt_count >= max_attempts:
        conn.execute(
            """
            UPDATE background_jobs
            SET status = ?, leased_by = '', leased_at = '', last_error = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (JOB_STATUS_FAILED, message, timestamp, timestamp, job_id),
        )
        return
    backoff_seconds = min(30, 2 ** max(attempt_count - 1))
    retry_at = datetime.fromtimestamp(datetime.now(UTC).timestamp() + backoff_seconds, tz=UTC).replace(microsecond=0).isoformat()
    conn.execute(
        """
        UPDATE background_jobs
        SET status = ?, leased_by = '', leased_at = '', available_at = ?, last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (JOB_STATUS_PENDING, retry_at, message, timestamp, job_id),
    )


def validate_document_target(
    conn: sqlite3.Connection,
    company_id: int,
    report_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    company = get_company_metadata(conn, company_id)
    if not company:
        raise KeyError("Company not found.")
    if report_id is None:
        return company, None
    report_row = conn.execute(
        "SELECT id, company_id, stage_id, template_id FROM reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not report_row:
        raise KeyError("Report not found.")
    report = row_to_dict(report_row)
    if int(report["company_id"]) != int(company_id):
        raise ValueError("report_id must belong to the same company.")
    return company, report


def document_normalized_output_path(upload_root: Path, document: dict[str, Any]) -> Path:
    stored = str(document.get("normalized_text_path") or "").strip()
    if stored:
        return Path(stored)
    return upload_root / str(document["company_id"]) / "normalized" / f"{int(document['id'])}-{Path(document['stored_name']).stem}.txt"


def create_document_record(
    conn: sqlite3.Connection,
    upload_root: Path,
    company_id: int,
    original_name: str,
    content: bytes,
    *,
    report_id: int | None = None,
    notes: str = "",
    mime_type: str = "",
    cleanup_paths: list[Path] | None = None,
) -> dict[str, Any]:
    _, report = validate_document_target(conn, company_id, report_id)
    normalized_report_id = int(report["id"]) if report else None
    safe_name = sanitize_filename(original_name)
    stored_name = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}-{safe_name}"
    company_dir = upload_root / str(company_id)
    company_dir.mkdir(parents=True, exist_ok=True)
    storage_path = company_dir / stored_name
    guessed_type = mime_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    timestamp = now_iso()

    if cleanup_paths is not None:
        cleanup_paths.append(storage_path)

    conn.execute(
        """
        INSERT INTO documents
        (company_id, report_id, original_name, stored_name, storage_path, mime_type, size_bytes, notes,
         normalized_text_path, normalized_status, normalized_format, normalized_method, normalized_notes,
         normalized_preview, normalized_updated_at, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '', '', '', ?)
        """,
        (
            company_id,
            normalized_report_id,
            original_name,
            stored_name,
            str(storage_path),
            guessed_type,
            len(content),
            notes,
            timestamp,
        ),
    )
    doc_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    normalized_dir = company_dir / "normalized"
    normalized_path = normalized_dir / f"{doc_id}-{Path(safe_name).stem}.txt"
    if cleanup_paths is not None:
        cleanup_paths.append(normalized_path)

    storage_path.write_bytes(content)
    conn.execute(
        """
        UPDATE documents
        SET normalized_text_path = ?, normalized_status = ?, normalized_notes = ?, normalized_updated_at = ?
        WHERE id = ?
        """,
        (
            str(normalized_path),
            DOCUMENT_STATUS_PENDING,
            "",
            now_iso(),
            doc_id,
        ),
    )
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    document = decorate_document_record(row_to_dict(row))
    if not document:
        raise KeyError("Document not found after save.")
    return document


def save_document(
    conn: sqlite3.Connection,
    upload_root: Path,
    company_id: int,
    original_name: str,
    content: bytes,
    report_id: int | None = None,
    notes: str = "",
    mime_type: str = "",
) -> dict[str, Any]:
    cleanup_paths: list[Path] = []
    normalized_report_id = int(report_id) if report_id not in (None, "") else None
    try:
        with savepoint(conn, "save_document"):
            document = create_document_record(
                conn,
                upload_root,
                company_id,
                original_name,
                content,
                report_id=normalized_report_id,
                notes=notes,
                mime_type=mime_type,
                cleanup_paths=cleanup_paths,
            )
            enqueue_document_normalization_job(conn, int(document["id"]))
        conn.commit()
        return document
    except Exception:
        conn.rollback()
        cleanup_written_paths(cleanup_paths)
        raise


def get_document(conn: sqlite3.Connection, document_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    item = row_to_dict(row)
    return decorate_document_record(item) if item else None


def document_status_record(conn: sqlite3.Connection, document_id: int) -> dict[str, Any] | None:
    document = get_document(conn, document_id)
    if not document:
        return None
    return {
        "id": int(document["id"]),
        "normalized_status": document["normalized_status"],
        "normalized_format": document.get("normalized_format", ""),
        "normalized_method": document.get("normalized_method", ""),
        "normalized_notes": document.get("normalized_notes", ""),
        "normalized_preview": document.get("normalized_preview", ""),
        "normalized_text_path": document.get("normalized_text_path", ""),
        "normalized_available": bool(document.get("normalized_available")),
        "normalized_updated_at": document.get("normalized_updated_at", ""),
        "status_url": document.get("status_url", ""),
        "download_url": document.get("download_url", ""),
        "normalized_url": document.get("normalized_url", ""),
    }


def normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").replace(";", ",").split(",")
    return [str(tag).strip() for tag in raw if str(tag).strip()]


def validate_report_source_payload(
    conn: sqlite3.Connection,
    report: dict[str, Any],
    payload: dict[str, Any],
    document_id: int | None,
    *,
    has_file: bool,
    url: str,
    snapshot_guidance_acknowledged: bool,
    link_only_reason: str,
) -> None:
    evidence_grade = str(payload.get("evidence_grade") or "").strip()
    if evidence_grade and evidence_grade not in {"F", "O", "M", "I", "V"}:
        raise ValueError("Invalid evidence grade.")

    confidence = str(payload.get("confidence") or "").strip()
    if confidence and confidence not in {"High", "Medium", "Low"}:
        raise ValueError("Invalid confidence value.")

    if document_id:
        document = get_document(conn, int(document_id))
        if not document:
            raise KeyError("Document not found.")
        if int(document["company_id"]) != int(report["company_id"]):
            raise ValueError("Sources can only link to documents from the same company.")

    for key in ("title", "source_type", "url", "citation", "notes", "link_only_reason"):
        if key in payload:
            validate_scalar_payload(payload.get(key), f"{key} must be plain text.")
    if "snapshot_guidance_acknowledged" in payload:
        parse_boolean_flag(payload.get("snapshot_guidance_acknowledged"), field_name="snapshot_guidance_acknowledged")
    if str(url or "").strip() and not document_id and not has_file:
        if not snapshot_guidance_acknowledged:
            raise ValueError(
                "URL-only sources require snapshot_guidance_acknowledged=true after reading the snapshot upload guidance."
            )
        if not link_only_reason.strip():
            raise ValueError("URL-only sources require link_only_reason explaining why no snapshot was uploaded.")


def validate_source_document(
    conn: sqlite3.Connection,
    report: dict[str, Any],
    document_id: int | None,
) -> None:
    if not document_id:
        return
    document = get_document(conn, int(document_id))
    if not document:
        raise KeyError("Document not found.")
    if int(document["company_id"]) != int(report["company_id"]):
        raise ValueError("Sources can only link to documents from the same company.")


def list_report_sources(conn: sqlite3.Connection, report_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT report_sources.*, documents.original_name AS document_name, documents.mime_type AS document_mime_type,
               documents.normalized_status, documents.normalized_format, documents.normalized_method,
               documents.normalized_notes, documents.normalized_preview, documents.normalized_text_path
        FROM report_sources
        LEFT JOIN documents ON documents.id = report_sources.document_id
        WHERE report_sources.report_id = ?
        ORDER BY report_sources.updated_at DESC, report_sources.id DESC
        """,
        (report_id,),
    ).fetchall()
    sources = []
    for row in rows:
        item = row_to_dict(row)
        item["tags"] = load_json(item.pop("tags_json"), [])
        decorate_source_record(item)
        sources.append(item)
    return sources


def get_report_source(conn: sqlite3.Connection, source_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT report_sources.*, documents.original_name AS document_name, documents.mime_type AS document_mime_type,
               documents.normalized_status, documents.normalized_format, documents.normalized_method,
               documents.normalized_notes, documents.normalized_preview, documents.normalized_text_path
        FROM report_sources
        LEFT JOIN documents ON documents.id = report_sources.document_id
        WHERE report_sources.id = ?
        """,
        (source_id,),
    ).fetchone()
    item = row_to_dict(row)
    if not item:
        return None
    item["tags"] = load_json(item.pop("tags_json"), [])
    return decorate_source_record(item)


def save_report_source(
    conn: sqlite3.Connection,
    upload_root: Path,
    report_id: int | None,
    payload: dict[str, Any],
    file_name: str | None = None,
    file_content: bytes | None = None,
    file_mime_type: str = "",
    file_origin: str = "",
) -> dict[str, Any]:
    source_report_id = int(report_id) if report_id not in (None, "") else None
    existing_source: dict[str, Any] | None = None
    has_file = bool(file_name and file_content is not None)
    if payload.get("id"):
        existing = conn.execute(
            "SELECT report_id FROM report_sources WHERE id = ?",
            (int(payload["id"]),),
        ).fetchone()
        if not existing:
            raise KeyError("Source not found.")
        source_report_id = int(existing["report_id"])
        existing_source = get_report_source(conn, int(payload["id"]))
    elif source_report_id is None:
        source_report_id = int(payload["report_id"])
    report = get_report(conn, source_report_id)
    if not report:
        raise KeyError("Report not found.")
    cleanup_paths: list[Path] = []
    timestamp = now_iso()
    tags = normalize_tags(payload.get("tags", existing_source.get("tags", []) if existing_source else ""))
    title = (
        payload.get("title")
        or (existing_source.get("title") if existing_source else "")
        or file_name
        or payload.get("url")
        or (existing_source.get("url") if existing_source else "")
        or "Untitled source"
    ).strip()
    source_type = payload.get("source_type", existing_source.get("source_type", "") if existing_source else "")
    evidence_grade = payload.get("evidence_grade", existing_source.get("evidence_grade", "") if existing_source else "")
    confidence = payload.get("confidence", existing_source.get("confidence", "") if existing_source else "")
    url = payload.get("url", existing_source.get("url", "") if existing_source else "")
    document_id = payload.get("document_id") or (existing_source.get("document_id") if existing_source else None) or None
    canonical_url = canonicalize_source_url(url)
    snapshot_guidance_acknowledged = parse_boolean_flag(
        payload.get(
            "snapshot_guidance_acknowledged",
            existing_source.get("snapshot_guidance_acknowledged", False) if existing_source else False,
        ),
        field_name="snapshot_guidance_acknowledged",
    )
    link_only_reason = str(
        payload.get("link_only_reason", existing_source.get("link_only_reason", "") if existing_source else "") or ""
    ).strip()
    citation = payload.get("citation", existing_source.get("citation", "") if existing_source else "")
    notes = payload.get("notes", existing_source.get("notes", "") if existing_source else "")
    validate_report_source_payload(
        conn,
        report,
        payload,
        int(document_id) if document_id else None,
        has_file=has_file,
        url=str(url or ""),
        snapshot_guidance_acknowledged=snapshot_guidance_acknowledged,
        link_only_reason=link_only_reason,
    )
    if document_id and not has_file:
        validate_source_document(conn, report, int(document_id))
    try:
        with savepoint(conn, "save_report_source"):
            capture_document: dict[str, Any] | None = None
            if has_file and file_name and file_content is not None:
                capture_document = create_document_record(
                    conn,
                    upload_root,
                    int(report["company_id"]),
                    file_name,
                    file_content,
                    report_id=source_report_id,
                    notes=notes,
                    mime_type=file_mime_type,
                    cleanup_paths=cleanup_paths,
                )
                document_id = int(capture_document["id"])
                enqueue_document_normalization_job(conn, document_id)
            elif document_id:
                document_id = int(document_id)
                capture_document = get_document(conn, document_id)
            else:
                document_id = None
            capture_kind = inferred_capture_kind(
                capture_kind=file_origin or "",
                document_id=document_id,
                url=str(url or ""),
            )
            capture_state = SOURCE_CAPTURE_LINK_ONLY
            capture_error = ""
            if document_id:
                capture_state, capture_error = source_capture_state_for_document(capture_document)
                snapshot_guidance_acknowledged = bool(
                    existing_source.get("snapshot_guidance_acknowledged", False) if existing_source else False
                )

            if payload.get("id"):
                source_id = int(payload["id"])
                conn.execute(
                    """
                    UPDATE report_sources
                    SET document_id = ?, title = ?, capture_kind = ?, source_type = ?, evidence_grade = ?, confidence = ?,
                        tags_json = ?, url = ?, canonical_url = ?, link_only_reason = ?,
                        snapshot_guidance_acknowledged = ?, capture_state = ?, capture_error = ?,
                        citation = ?, notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        document_id,
                        title,
                        capture_kind,
                        source_type,
                        evidence_grade,
                        confidence,
                        dump_json(tags),
                        url,
                        canonical_url,
                        link_only_reason,
                        1 if snapshot_guidance_acknowledged else 0,
                        capture_state,
                        capture_error,
                        citation,
                        notes,
                        timestamp,
                        source_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO report_sources
                    (report_id, document_id, title, capture_kind, source_type, evidence_grade, confidence,
                     tags_json, url, canonical_url, link_only_reason, snapshot_guidance_acknowledged,
                     capture_state, capture_error, citation, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_report_id,
                        document_id,
                        title,
                        capture_kind,
                        source_type,
                        evidence_grade,
                        confidence,
                        dump_json(tags),
                        url,
                        canonical_url,
                        link_only_reason,
                        1 if snapshot_guidance_acknowledged else 0,
                        capture_state,
                        capture_error,
                        citation,
                        notes,
                        timestamp,
                        timestamp,
                    ),
                )
                source_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            if document_id:
                sync_report_source_capture_for_document(conn, int(document_id))

            source = get_report_source(conn, source_id)
            if not source:
                raise KeyError("Source not found after save.")
        conn.commit()
        return source
    except Exception:
        conn.rollback()
        cleanup_written_paths(cleanup_paths)
        raise


def delete_report_source(conn: sqlite3.Connection, source_id: int) -> None:
    row = conn.execute("SELECT report_id FROM report_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        raise KeyError("Source not found.")
    source_key = str(source_id)
    for report_row in conn.execute("SELECT id, field_sources_json FROM reports").fetchall():
        field_sources = load_json(report_row["field_sources_json"], {})
        changed = False
        for entry in field_sources.values():
            if not isinstance(entry, dict):
                continue
            source_ids = entry.get("source_ids", [])
            filtered = [item for item in source_ids if str(item) != source_key]
            if filtered != source_ids:
                entry["source_ids"] = filtered
                changed = True
        if changed:
            conn.execute(
                "UPDATE reports SET field_sources_json = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                (dump_json(field_sources), now_iso(), int(report_row["id"])),
            )
    conn.execute("DELETE FROM report_sources WHERE id = ?", (source_id,))
    conn.commit()


def normalization_failure_stub(output_path: Path, *, original_name: str, notes: str) -> dict[str, str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# {original_name}\n\n"
        "## Metadata\n"
        f"- Notes: {notes}\n\n"
        "## LLM View\n"
        "(Normalization failed. Use the original file for final verification.)\n"
    )
    output_path.write_text(body, encoding="utf-8")
    return {
        "status": DOCUMENT_STATUS_FAILED,
        "format": "metadata-only",
        "method": "fallback",
        "notes": notes,
        "preview": body[:700].strip(),
        "path": str(output_path),
    }


def apply_document_normalization(
    conn: sqlite3.Connection,
    document_id: int,
    normalized: dict[str, str],
) -> None:
    conn.execute(
        """
        UPDATE documents
        SET normalized_text_path = ?, normalized_status = ?, normalized_format = ?, normalized_method = ?,
            normalized_notes = ?, normalized_preview = ?, normalized_updated_at = ?
        WHERE id = ?
        """,
        (
            normalized["path"],
            normalized["status"],
            normalized["format"],
            normalized["method"],
            normalized["notes"],
            normalized["preview"],
            now_iso(),
            document_id,
        ),
    )
    sync_report_source_capture_for_document(conn, document_id)


def process_document_normalization_job(
    db_file: Path,
    upload_root: Path,
    job: dict[str, Any],
) -> None:
    document_id = int(job.get("document_id") or 0)
    if not document_id:
        conn = connect(db_file)
        try:
            fail_background_job(
                conn,
                int(job["id"]),
                attempt_count=int(job.get("attempt_count") or 1),
                max_attempts=int(job.get("max_attempts") or MAX_JOB_ATTEMPTS),
                message="Background job is missing document_id.",
            )
            conn.commit()
        finally:
            conn.close()
        return

    conn = connect(db_file)
    try:
        document_row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        document = row_to_dict(document_row)
    finally:
        conn.close()
    if not document:
        conn = connect(db_file)
        try:
            fail_background_job(
                conn,
                int(job["id"]),
                attempt_count=int(job.get("attempt_count") or 1),
                max_attempts=int(job.get("max_attempts") or MAX_JOB_ATTEMPTS),
                message="Document not found for background normalization job.",
            )
            conn.commit()
        finally:
            conn.close()
        return

    storage_path = Path(document["storage_path"])
    normalized_path = document_normalized_output_path(upload_root, document)
    if storage_path.exists():
        normalized = normalize_document_file(
            storage_path,
            normalized_path,
            original_name=document["original_name"],
            mime_type=document["mime_type"],
        )
    else:
        normalized = normalization_failure_stub(
            normalized_path,
            original_name=document["original_name"],
            notes="Stored artifact is missing.",
        )

    conn = connect(db_file)
    try:
        with savepoint(conn, "complete_document_job"):
            apply_document_normalization(conn, document_id, normalized)
            complete_background_job(conn, int(job["id"]))
        conn.commit()
    finally:
        conn.close()


def process_next_background_job(
    db_file: Path,
    upload_root: Path,
    worker_id: str,
    *,
    lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
) -> bool:
    conn = connect(db_file)
    try:
        job = retry_busy(lambda: lease_background_job(conn, worker_id, lease_seconds=lease_seconds))
        if not job:
            return False
        conn.commit()
    finally:
        conn.close()

    try:
        if str(job.get("kind") or "") == JOB_KIND_DOCUMENT_NORMALIZATION:
            process_document_normalization_job(db_file, upload_root, job)
        else:
            conn = connect(db_file)
            try:
                fail_background_job(
                    conn,
                    int(job["id"]),
                    attempt_count=int(job.get("attempt_count") or 1),
                    max_attempts=int(job.get("max_attempts") or MAX_JOB_ATTEMPTS),
                    message=f"Unsupported background job kind: {job.get('kind')}",
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:
        conn = connect(db_file)
        try:
            fail_background_job(
                conn,
                int(job["id"]),
                attempt_count=int(job.get("attempt_count") or 1),
                max_attempts=int(job.get("max_attempts") or MAX_JOB_ATTEMPTS),
                message=str(exc),
            )
            if job.get("document_id"):
                document_row = conn.execute("SELECT * FROM documents WHERE id = ?", (int(job["document_id"]),)).fetchone()
                document = row_to_dict(document_row)
                if document:
                    normalized_path = document_normalized_output_path(upload_root, document)
                    normalized = normalization_failure_stub(
                        normalized_path,
                        original_name=document["original_name"],
                        notes=str(exc),
                    )
                    apply_document_normalization(conn, int(document["id"]), normalized)
            conn.commit()
        finally:
            conn.close()
    return True


def drain_background_jobs(
    db_file: Path,
    upload_root: Path,
    *,
    worker_id: str = "test-worker",
    max_jobs: int = 20,
) -> int:
    processed = 0
    while processed < max_jobs and process_next_background_job(db_file, upload_root, worker_id):
        processed += 1
    return processed


def backfill_document_normalization(conn: sqlite3.Connection, upload_root: Path) -> int:
    updated = 0
    rows = conn.execute(
        """
        SELECT * FROM documents
        WHERE normalized_status = '' OR normalized_text_path = ''
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        item = row_to_dict(row)
        if not item:
            continue
        storage_path = Path(item["storage_path"])
        if not storage_path.exists():
            continue
        company_dir = upload_root / str(item["company_id"]) / "normalized"
        normalized_path = company_dir / f"{item['id']}-{Path(item['stored_name']).stem}.txt"
        normalized = normalize_document_file(
            storage_path,
            normalized_path,
            original_name=item["original_name"],
            mime_type=item["mime_type"],
        )
        apply_document_normalization(conn, int(item["id"]), normalized)
        updated += 1
    conn.commit()
    return updated


def evaluate_rule(comparator: str, current_value: float | None, threshold: float | None) -> bool:
    if current_value is None or threshold is None:
        return False
    if comparator == "<":
        return current_value < threshold
    if comparator == "<=":
        return current_value <= threshold
    if comparator == ">":
        return current_value > threshold
    if comparator == ">=":
        return current_value >= threshold
    if comparator in ("=", "=="):
        return current_value == threshold
    return False


def list_monitoring_rules(
    conn: sqlite3.Connection, company_id: int | None = None, bucket: str | None = None
) -> list[dict[str, Any]]:
    params: list[Any] = []
    clauses = []
    if company_id:
        clauses.append("monitoring_rules.company_id = ?")
        params.append(company_id)
    if bucket:
        clauses.append("companies.bucket = ?")
        params.append(bucket)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT monitoring_rules.*, companies.ticker, companies.name AS company_name
        FROM monitoring_rules
        JOIN companies ON companies.id = monitoring_rules.company_id
        {where}
        ORDER BY monitoring_rules.triggered DESC, monitoring_rules.updated_at DESC
        """,
        params,
    ).fetchall()
    return [row_to_dict(row) for row in rows if row]


def save_monitoring_rule(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    allow_report_owned_structure: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    timestamp = now_iso()
    existing_rule = None
    if payload.get("id"):
        existing_rule = conn.execute("SELECT * FROM monitoring_rules WHERE id = ?", (int(payload["id"]),)).fetchone()
        if not existing_rule:
            raise KeyError("Monitoring rule not found.")

    current_value = payload.get("current_value", existing_rule["current_value"] if existing_rule else None)
    threshold = payload.get("threshold_value", existing_rule["threshold_value"] if existing_rule else None)
    current_number = float(current_value) if current_value not in ("", None) else None
    threshold_number = float(threshold) if threshold not in ("", None) else None
    comparator = payload.get("comparator", existing_rule["comparator"] if existing_rule else "<=") or "<="
    if comparator not in {"<", "<=", ">", ">=", "=", "=="}:
        raise ValueError("Invalid comparator.")
    metric_name = str(payload.get("metric_name", existing_rule["metric_name"] if existing_rule else "")).strip()
    unit = str(payload.get("unit", existing_rule["unit"] if existing_rule else "") or "")
    source = str(payload.get("source", existing_rule["source"] if existing_rule else "") or "")
    report_rule_key = str(payload.get("report_rule_key", existing_rule["report_rule_key"] if existing_rule else "") or "").strip()
    notes = str(payload.get("notes", existing_rule["notes"] if existing_rule else "") or "")
    if not report_rule_key and payload.get("report_id"):
        report_rule_key = objective_rule_key(metric_name, comparator, threshold_number, unit)
    if existing_rule and existing_rule["report_id"] and not allow_report_owned_structure:
        if (
            metric_name != str(existing_rule["metric_name"])
            or comparator != str(existing_rule["comparator"])
            or threshold_number != existing_rule["threshold_value"]
            or unit != str(existing_rule["unit"] or "")
            or source != str(existing_rule["source"] or "")
            or report_rule_key != str(existing_rule["report_rule_key"] or "")
        ):
            raise ValueError("Report-owned monitoring rules can only update current_value and notes.")
        metric_name = str(existing_rule["metric_name"])
        comparator = str(existing_rule["comparator"])
        threshold_number = existing_rule["threshold_value"]
        unit = str(existing_rule["unit"] or "")
        source = str(existing_rule["source"] or "")
        report_rule_key = str(existing_rule["report_rule_key"] or "")
    triggered = 1 if evaluate_rule(comparator, current_number, threshold_number) else 0
    if payload.get("id"):
        rule_id = int(payload["id"])
        conn.execute(
            """
            UPDATE monitoring_rules
            SET report_rule_key = ?, metric_name = ?, comparator = ?, threshold_value = ?, unit = ?,
                current_value = ?, source = ?, triggered = ?, notes = ?,
                last_checked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                report_rule_key,
                metric_name,
                comparator,
                threshold_number,
                unit,
                current_number,
                source,
                triggered,
                notes,
                timestamp if current_number is not None else payload.get("last_checked_at", existing_rule["last_checked_at"]),
                timestamp,
                rule_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO monitoring_rules
            (company_id, report_id, report_rule_key, metric_name, comparator, threshold_value, unit, current_value,
             source, triggered, notes, last_checked_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(payload["company_id"]),
                payload.get("report_id"),
                report_rule_key,
                metric_name,
                comparator,
                threshold_number,
                unit,
                current_number,
                source,
                triggered,
                notes,
                timestamp if current_number is not None else "",
                timestamp,
                timestamp,
            ),
        )
        rule_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    if commit:
        conn.commit()
    row = conn.execute("SELECT * FROM monitoring_rules WHERE id = ?", (rule_id,)).fetchone()
    return row_to_dict(row)


def create_monitoring_rules_from_report(
    conn: sqlite3.Connection,
    report: dict[str, Any] | None,
    *,
    desired_rules: list[dict[str, Any]] | None = None,
) -> None:
    if not report:
        return
    normalized_rules = (
        normalize_objective_rules(desired_rules)
        if desired_rules is not None
        else normalize_objective_rules(report.get("watchlist_objective_rules") or [])
    )
    if report.get("result") != RESULT_WATCHLIST:
        normalized_rules = []

    existing_rows = conn.execute(
        """
        SELECT *
        FROM monitoring_rules
        WHERE report_id = ?
        ORDER BY id
        """,
        (int(report["id"]),),
    ).fetchall()
    existing_by_rule_key = {
        monitoring_rule_report_key(row_to_dict(row) or {}): row_to_dict(row) or {}
        for row in existing_rows
    }
    desired_rule_keys = {rule["rule_key"] for rule in normalized_rules}
    for row in existing_rows:
        rule_key = monitoring_rule_report_key(row_to_dict(row) or {})
        if rule_key in desired_rule_keys:
            continue
        conn.execute("DELETE FROM monitoring_rules WHERE id = ?", (int(row["id"]),))

    for rule in normalized_rules:
        existing = existing_by_rule_key.get(rule["rule_key"]) or {}
        payload = {
            "id": existing.get("id"),
            "company_id": report["company_id"],
            "report_id": report["id"],
            "report_rule_key": rule["rule_key"],
            "metric_name": rule["metric_name"],
            "comparator": rule["comparator"],
            "threshold_value": rule["threshold_value"],
            "unit": rule.get("unit", ""),
            "current_value": existing.get("current_value", rule.get("current_value")),
            "source": rule.get("source", "") or "Report objective rule",
            "notes": existing.get("notes", rule.get("notes", "")),
        }
        save_monitoring_rule(
            conn,
            payload,
            allow_report_owned_structure=True,
            commit=False,
        )
    conn.commit()
