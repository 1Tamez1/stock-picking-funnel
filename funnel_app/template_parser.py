from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BOLD_LABEL_RE = re.compile(r"^\*\*(.+?)\*\*:\s*(.*)$")
BULLET_LABEL_RE = re.compile(r"^[-*]\s+([^:\n]{2,120}):\s*(.*)$")
TOTAL_RE = re.compile(r"^\*\*(Total\s+[^:]+):\s*_*[\s_]*/\s*(\d+)\*\*\s*$", re.I)
SCORE_MAX_RE = re.compile(r"\((\d+)\s+points?\)", re.I)
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")

METRIC_WORDS = {
    "capex",
    "capital",
    "cash",
    "coverage",
    "currency",
    "debt",
    "dividend",
    "ebitda",
    "earnings",
    "enterprise value",
    "equity",
    "ev",
    "fcf",
    "gross margin",
    "interest",
    "intrinsic value",
    "liquidity",
    "margin",
    "market capitalization",
    "net cash",
    "net debt",
    "owner earnings",
    "price",
    "reinvestment",
    "reserve",
    "revenue",
    "roe",
    "roic",
    "shares",
    "value",
    "working-capital",
    "working capital",
}

DATE_WORDS = {"date", "review date", "fiscal year-end", "year-end"}
OPTION_DELIMITER_RE = re.compile(r"\s+/\s+")


@dataclass
class FieldCandidate:
    label: str
    kind: str
    section_id: str
    help_text: str = ""
    options: list[str] = field(default_factory=list)
    max_value: float | None = None
    explicit_id: str = ""
    origin: str = ""


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:72] or "field"


def stable_id(*parts: str) -> str:
    base = "-".join(slugify(part) for part in parts if part)
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"[:96]


def custom_compat_id(section_id: str, label: str) -> str:
    return f"custom-{section_id}-{slugify(label)}"


def strip_markdown(value: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"`(.*?)`", r"\1", value)
    return value.strip()


def contains_term(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text))


def split_delimited_options(value: str) -> list[str]:
    if not OPTION_DELIMITER_RE.search(value):
        return []
    return [strip_markdown(part) for part in OPTION_DELIMITER_RE.split(value) if strip_markdown(part)]


def infer_question_kind(label: str) -> tuple[str, list[str], float | None]:
    normalized = strip_markdown(label).rstrip("?").strip().lower()
    if normalized.startswith(("what ", "why ", "how ", "who ", "where ", "when ", "which ")):
        return "textarea", [], None
    if normalized.startswith(("is ", "are ", "can ", "do ", "does ", "did ", "has ", "have ", "will ", "would ", "could ", "should ")):
        return "select", ["Yes", "No", "Unknown"], None
    return "textarea", [], None


def infer_kind(label: str, trailing_text: str = "") -> tuple[str, list[str], float | None]:
    normalized = label.lower()
    payload = trailing_text.strip()

    if normalized in DATE_WORDS or normalized.endswith(" date") or normalized.startswith("review date"):
        return "date", [], None

    if payload and len(payload) <= 120:
        options = split_delimited_options(payload)
        if len(options) >= 2:
            return "select", options, None

    if normalized.startswith(("what ", "why ", "how ", "who ", "where ", "when ", "which ")):
        return "textarea", [], None

    if normalized.startswith(("is ", "are ", "can ", "do ", "does ", "did ", "has ", "have ", "will ", "would ", "could ", "should ", "if ")):
        return "textarea", [], None

    if normalized.startswith("evidence "):
        return "textarea", [], None

    if normalized.endswith(" opportunities") or normalized.endswith(" trend"):
        return "text", [], None

    if normalized in {"currency", "reporting currency"} or normalized.endswith(" currency"):
        return "text", [], None

    if normalized == "price":
        return "text", [], None

    if (
        "quick read" in normalized
        or normalized.endswith(" read")
        or normalized.endswith(" view")
        or normalized.endswith(" built")
        or " inherited from " in normalized
        or normalized.endswith(" reviewed")
        or " case-reviewed" in normalized
    ):
        return "text", [], None

    if normalized.endswith(" assumption"):
        return "text", [], None

    if normalized.endswith(" considerations"):
        return "text", [], None

    if normalized in {
        "current best alternative use of capital",
        "enterprise-first or equity-first",
        "existing position?",
        "knowability of value range",
        "liquidity / order-type considerations",
    } or " read inherited" in normalized:
        return "text", [], None

    if "pass /" in payload.lower() or "watchlist /" in payload.lower():
        options = [strip_markdown(part) for part in payload.split("/") if strip_markdown(part)]
        return "select", options, None

    if "score" in normalized:
        return "number", [], None

    if normalized in {
        "apparent margin of safety",
        "business in two sentences",
        "downstream issues to preserve",
        "main disconfirming evidence",
        "most important bias risk",
        "what must be true",
        "why this might be interesting",
        "why this might be wrong",
    }:
        return "textarea", [], None

    for word in METRIC_WORDS:
        if contains_term(normalized, word):
            return "metric", [], None

    if any(word in normalized for word in ("explain", "describe", "notes", "reason", "thesis", "risk", "summary")):
        return "textarea", [], None

    return "text", [], None


def split_table_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [strip_markdown(cell.strip()) for cell in value.split("|")]


def looks_like_table_options(value: str) -> bool:
    parts = split_delimited_options(value)
    return len(parts) >= 2 and all(len(part) <= 40 for part in parts)


def infer_table_cell_kind(header: str, sample: str) -> tuple[str, list[str], float | None]:
    normalized = header.lower()
    if looks_like_table_options(sample):
        return "select", split_delimited_options(sample), None
    if normalized in {"result", "answer", "confidence", "evidence grade", "rating"} and sample:
        return infer_kind(header, sample)
    if "confidence" in normalized:
        return "select", ["High", "Medium", "Low"], None
    if "evidence" in normalized and "grade" in normalized:
        return "select", ["F", "O", "M", "I", "V"], None
    if "result" in normalized:
        return "select", ["Pass", "Watchlist", "Archive"], None
    if "rating" in normalized:
        return "select", ["Strong", "Adequate", "Weak", "Unknown"], None
    if "notes" in normalized or "how to verify" in normalized or "main note" in normalized:
        return "textarea", [], None
    if "source" in normalized or "stage" in normalized or "action" in normalized:
        return "text", [], None
    return "textarea", [], None


def parse_markdown_template(markdown: str) -> dict[str, Any]:
    """Convert an editable markdown questionnaire into renderable sections and fields.

    The parser intentionally keeps the original markdown as the source of truth.
    It extracts likely fillable fields from common questionnaire patterns, while
    preserving the surrounding text for analyst guidance.
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    field_counts: dict[str, int] = {}
    last_prompt = ""
    current_score_max: float | None = None
    table_headers: list[str] | None = None
    table_started = False
    table_row_count = 0
    list_mode = ""

    def ensure_section() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "id": stable_id("overview"),
                "title": "Overview",
                "level": 1,
                "body": [],
                "fields": [],
            }
            sections.append(current)
        return current

    def add_field(candidate: FieldCandidate) -> None:
        section = ensure_section()
        key = f"{candidate.section_id}:{candidate.label}"
        field_counts[key] = field_counts.get(key, 0) + 1
        index = field_counts[key]
        field_id = candidate.explicit_id or stable_id(candidate.section_id, candidate.label, str(index))
        field = {
            "id": field_id,
            "label": candidate.label,
            "kind": candidate.kind,
            "help": candidate.help_text,
            "options": candidate.options,
            "max": candidate.max_value,
        }
        if candidate.origin:
            field["origin"] = candidate.origin
        section["fields"].append(field)

    lines = markdown.splitlines()
    for line_index, raw_line in enumerate(lines):
        next_nonempty = ""
        for candidate in lines[line_index + 1 :]:
            stripped = candidate.strip()
            if stripped:
                next_nonempty = stripped
                break
        heading = HEADING_RE.match(raw_line)
        if heading:
            level = len(heading.group(1))
            title = strip_markdown(heading.group(2))
            if level <= 3:
                table_headers = None
                table_started = False
                table_row_count = 0
                list_mode = ""
                current = {
                    "id": stable_id(title),
                    "title": title,
                    "level": level,
                    "body": [],
                    "fields": [],
                }
                sections.append(current)
                score_match = SCORE_MAX_RE.search(title)
                current_score_max = float(score_match.group(1)) if score_match else None
                last_prompt = ""
                continue

        section = ensure_section()
        section["body"].append(raw_line)

        text = raw_line.strip()
        if not text or text.startswith("|") or text == "---":
            if not text.startswith("|"):
                table_headers = None
                table_started = False
                table_row_count = 0
            if not text.startswith("|"):
                continue

        if text.startswith("|"):
            cells = split_table_row(text)
            if TABLE_SEPARATOR_RE.match(text):
                table_started = table_headers is not None
                table_row_count = 0
                continue
            if table_headers is None or not table_started:
                table_headers = cells
                table_started = False
                table_row_count = 0
                continue
            if table_headers and table_started:
                table_row_count += 1
                row = cells + [""] * max(0, len(table_headers) - len(cells))
                first_header = table_headers[0] if table_headers else "Row"
                row_label = row[0] or f"{first_header} {table_row_count}"
                if (
                    row[0] == ""
                    and first_header.lower() in {"what must be true?", "business claim that must be true"}
                ):
                    prefix = "What must be true?" if first_header.lower() == "what must be true?" else "Business claim that must be true"
                    thesis_label = f"{prefix} {table_row_count} - Thesis condition"
                    add_field(
                        FieldCandidate(
                            label=thesis_label,
                            kind="textarea",
                            section_id=section["id"],
                            help_text=f"Table: {first_header}",
                            explicit_id=custom_compat_id(section["id"], thesis_label),
                            origin="thesis_condition",
                        )
                    )
                for index, header in enumerate(table_headers[1:], start=1):
                    sample = row[index] if index < len(row) else ""
                    if not header:
                        continue
                    if header.lower() in {"default action"}:
                        continue
                    label = row_label if header.lower() == "answer" else f"{row_label} - {header}"
                    kind, options, max_value = infer_table_cell_kind(header, sample)
                    add_field(
                        FieldCandidate(
                            label=label,
                            kind=kind,
                            section_id=section["id"],
                            help_text=f"Table: {first_header} / {header}",
                            options=options,
                            max_value=max_value,
                        )
                )
                continue

        table_headers = None
        table_started = False
        table_row_count = 0

        lowered = text.lower()
        if lowered == "questions:":
            list_mode = "questions"
            last_prompt = ""
            continue
        if lowered in {"check any that apply.", "mark any that apply:", "mark any that apply."}:
            list_mode = "checkbox"
            last_prompt = ""
            continue
        if lowered == "most important bias risk:":
            list_mode = ""
            last_prompt = "Most important bias risk"
            continue
        if lowered.startswith("write the handoff to"):
            list_mode = "handoff"
            last_prompt = ""
            continue
        if lowered in {
            "default screening posture:",
            "good examples:",
            "hard-fail items:",
            "next step:",
            "pass screening requires:",
            "rule:",
            "screening formula:",
            "screening standard:",
            "stress question:",
            "traits:",
            "business underwriting must prove next:",
        }:
            list_mode = "ignore"
            last_prompt = ""
            continue

        if list_mode == "questions":
            if text.startswith("- "):
                label = strip_markdown(text[2:].strip())
                kind, options, max_value = infer_question_kind(label)
                add_field(
                    FieldCandidate(
                        label=label,
                        kind=kind,
                        section_id=section["id"],
                        help_text="Questions block",
                        options=options,
                        max_value=max_value,
                        explicit_id=custom_compat_id(section["id"], label),
                        origin="question",
                    )
                )
                last_prompt = ""
                continue
            list_mode = ""

        if list_mode == "checkbox":
            if text.startswith("- "):
                if next_nonempty.lower().startswith("**answer**:"):
                    list_mode = ""
                else:
                    label = strip_markdown(text[2:].strip())
                    add_field(
                        FieldCandidate(
                            label=label,
                            kind="checkbox",
                            section_id=section["id"],
                            help_text="Checklist",
                            explicit_id=custom_compat_id(section["id"], label),
                            origin="checkbox",
                        )
                    )
                    last_prompt = ""
                    continue
            list_mode = ""

        if list_mode == "handoff":
            numbered = re.match(r"^(\d+)\.\s*$", text)
            if numbered:
                label = f"Business Underwriting handoff {numbered.group(1)}"
                add_field(
                    FieldCandidate(
                        label=label,
                        kind="textarea",
                        section_id=section["id"],
                        help_text="Business Underwriting handoff",
                        explicit_id=custom_compat_id(section["id"], label),
                        origin="handoff_item",
                    )
                )
                last_prompt = ""
                continue
            list_mode = ""

        if list_mode == "ignore":
            if text.startswith("- "):
                last_prompt = ""
                continue
            list_mode = ""

        if section.get("title") == "If It Is Archived" and text.startswith("- ") and not text.endswith(":"):
            label = strip_markdown(text[2:].strip())
            add_field(
                FieldCandidate(
                    label=label,
                    kind="textarea",
                    section_id=section["id"],
                    help_text="Archive follow-up",
                    explicit_id=custom_compat_id(section["id"], label),
                    origin="archive_prompt",
                )
            )
            last_prompt = ""
            continue

        if text.startswith("- ") and not text.endswith(":"):
            last_prompt = strip_markdown(text[2:].strip())
            if text.startswith("- **"):
                pass
            else:
                inline_question = last_prompt
                choice_match = re.match(r"^(.+?\?)\s+([^?].*?/.*)$", inline_question)
                if choice_match:
                    label = strip_markdown(choice_match.group(1))
                    payload = strip_markdown(choice_match.group(2))
                    kind, options, max_value = infer_kind(label, payload)
                    add_field(
                        FieldCandidate(
                            label=label,
                            kind=kind,
                            section_id=section["id"],
                            options=options,
                            max_value=max_value,
                        )
                    )
                    continue
                if next_nonempty.lower().startswith("**answer**:"):
                    continue
                if "?" in inline_question:
                    kind, options, max_value = infer_question_kind(inline_question)
                    add_field(
                        FieldCandidate(
                            label=inline_question,
                            kind=kind,
                            section_id=section["id"],
                            options=options,
                            max_value=max_value,
                        )
                    )
                    continue

        total_match = TOTAL_RE.match(text)
        if total_match:
            label = strip_markdown(total_match.group(1))
            add_field(
                FieldCandidate(
                    label=label,
                    kind="number",
                    section_id=section["id"],
                    max_value=float(total_match.group(2)),
                )
            )
            continue

        bold = BOLD_LABEL_RE.match(text)
        if bold:
            label = strip_markdown(bold.group(1))
            payload = strip_markdown(bold.group(2))
            if label.lower() == "answer" and last_prompt:
                label = last_prompt
                kind = "textarea"
                options: list[str] = []
                max_value = None
            else:
                kind, options, max_value = infer_kind(label, payload)
                if label.lower() == "score" and current_score_max:
                    max_value = current_score_max
            add_field(
                FieldCandidate(
                    label=label,
                    kind=kind,
                    section_id=section["id"],
                    options=options,
                    max_value=max_value,
                )
            )
            continue

        bullet = BULLET_LABEL_RE.match(text)
        if bullet:
            label = strip_markdown(bullet.group(1))
            payload = strip_markdown(bullet.group(2))
            kind, options, max_value = infer_kind(label, payload)
            if "watchlist" in section.get("title", "").lower():
                kind = "text"
                options = []
                max_value = None
            add_field(
                FieldCandidate(
                    label=label,
                    kind=kind,
                    section_id=section["id"],
                    options=options,
                    max_value=max_value,
                )
            )

    normalized_sections = []
    all_fields = []
    for section in sections:
        body = "\n".join(section.pop("body")).strip()
        section["body_markdown"] = body
        normalized_sections.append(section)
        for item in section["fields"]:
            item["section_id"] = section["id"]
            all_fields.append(item)

    return {
        "schema_version": 1,
        "section_count": len(normalized_sections),
        "field_count": len(all_fields),
        "sections": normalized_sections,
        "fields": all_fields,
    }
