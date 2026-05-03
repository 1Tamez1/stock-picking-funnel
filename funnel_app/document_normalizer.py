from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET


DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
PPTX_TEXT_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
XLSX_MAIN_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".log"}
DELIMITED_EXTENSIONS = {".csv", ".tsv"}
JSON_EXTENSIONS = {".json"}
HTML_EXTENSIONS = {".html", ".htm"}
SHEET_EXTENSIONS = {".xlsx", ".xlsm"}
SLIDE_EXTENSIONS = {".pptx", ".pptm"}


@dataclass
class NormalizedDocument:
    status: str
    format: str
    method: str
    notes: str
    text: str


def normalize_document_file(
    source_path: Path,
    output_path: Path,
    *,
    original_name: str = "",
    mime_type: str = "",
) -> dict[str, str]:
    normalized = extract_document_text(source_path, original_name=original_name, mime_type=mime_type)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(normalized.text, encoding="utf-8")
    preview = build_preview(normalized.text)
    return {
        "status": normalized.status,
        "format": normalized.format,
        "method": normalized.method,
        "notes": normalized.notes,
        "preview": preview,
        "path": str(output_path),
    }


def extract_document_text(
    source_path: Path,
    *,
    original_name: str = "",
    mime_type: str = "",
) -> NormalizedDocument:
    suffix = source_path.suffix.lower()
    name = original_name or source_path.name
    title = f"# {name}"
    metadata = []
    if mime_type:
        metadata.append(f"- MIME type: {mime_type}")
    metadata.append(f"- Original file: {name}")

    try:
        if suffix in TEXT_EXTENSIONS:
            body = read_text_file(source_path)
            return build_result(title, metadata, body, "ready", "plain-text", "native-text")
        if suffix in DELIMITED_EXTENSIONS:
            body = delimited_to_markdown(source_path, "\t" if suffix == ".tsv" else ",")
            return build_result(title, metadata, body, "ready", "markdown-table", "csv-table")
        if suffix in JSON_EXTENSIONS:
            body = json.dumps(json.loads(read_text_file(source_path)), indent=2, ensure_ascii=False)
            return build_result(title, metadata, body, "ready", "json-text", "json-pretty")
        if suffix == ".pdf":
            body = extract_pdf_text(source_path)
            notes = "Layout-preserving PDF text. Charts and images should be checked against the original file."
            return build_result(title, metadata, body, "ready" if body.strip() else "limited", "layout-text", "pdftotext", notes)
        if suffix in HTML_EXTENSIONS:
            body = html_to_text(source_path)
            return build_result(title, metadata, body, "ready", "html-outline", "html-parser")
        if suffix == ".docx":
            body = docx_to_text(source_path)
            return build_result(title, metadata, body, "ready", "document-outline", "docx-xml")
        if suffix in {".doc", ".rtf", ".rtfd"}:
            body = textutil_to_text(source_path)
            return build_result(title, metadata, body, "ready" if body.strip() else "limited", "document-outline", "textutil")
        if suffix in SHEET_EXTENSIONS:
            body = xlsx_to_text(source_path)
            return build_result(title, metadata, body, "ready", "sheet-markdown", "xlsx-xml")
        if suffix in SLIDE_EXTENSIONS:
            body = pptx_to_text(source_path)
            notes = "Slide text extracted. Layout, charts, and speaker notes should be checked against the original file."
            return build_result(title, metadata, body, "ready", "slide-outline", "pptx-xml", notes)
    except Exception as exc:
        notes = f"Normalization error: {exc}"
        body = unsupported_stub(name, notes)
        return NormalizedDocument("failed", "metadata-only", "fallback", notes, body)

    notes = "No structured extractor is available for this file type yet. Use the original file for final verification."
    body = unsupported_stub(name, notes)
    return NormalizedDocument("limited", "metadata-only", "fallback", notes, body)


def build_result(
    title: str,
    metadata: list[str],
    body: str,
    status: str,
    format_name: str,
    method: str,
    notes: str = "",
) -> NormalizedDocument:
    clean_body = sanitize_text(body)
    parts = [title, "", "## Metadata", *metadata]
    if notes:
        parts.append(f"- Notes: {notes}")
    parts.extend(["", "## LLM View", clean_body or "(No text could be extracted.)"])
    return NormalizedDocument(status, format_name, method, notes, "\n".join(parts).strip() + "\n")


def build_preview(value: str, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def sanitize_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def delimited_to_markdown(path: Path, delimiter: str) -> str:
    rows = list(csv.reader(path.read_text(encoding="utf-8", errors="replace").splitlines(), delimiter=delimiter))
    return rows_to_markdown(rows, heading="Table")


def rows_to_markdown(rows: list[list[str]], *, heading: str = "") -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    body = padded[1:] or [[""] * width]
    lines = []
    if heading:
        lines.extend([f"### {heading}", ""])
    lines.append("| " + " | ".join(cell.strip() for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    lines.extend("| " + " | ".join(cell.strip() for cell in row) + " |" for row in body)
    return "\n".join(lines)


def extract_pdf_text(path: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is not installed")
    result = subprocess.run(
        [pdftotext, "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


class SourceHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.current: list[str] = []
        self.table: list[list[str]] = []
        self.row: list[str] = []
        self.cell: list[str] = []
        self.in_table = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "p", "div", "section", "article", "li", "br"}:
            self.flush_text()
        if tag == "table":
            self.flush_text()
            self.in_table = True
            self.table = []
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self.row.append("".join(self.cell).strip())
            self.cell = []
        elif tag == "tr":
            if self.row:
                self.table.append(self.row)
            self.row = []
        elif tag == "table":
            if self.table:
                self.lines.append(rows_to_markdown(self.table, heading="HTML table"))
            self.table = []
            self.in_table = False
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4"}:
            self.flush_text()

    def handle_data(self, data: str) -> None:
        if self.in_table and self.cell is not None:
            self.cell.append(data)
        else:
            self.current.append(data)

    def flush_text(self) -> None:
        text = "".join(self.current).strip()
        self.current = []
        if text:
            self.lines.append(text)


def html_to_text(path: Path) -> str:
    parser = SourceHtmlParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.flush_text()
    return "\n\n".join(item for item in parser.lines if item.strip())


def docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find("w:body", DOCX_NS)
    if body is None:
        return ""
    blocks: list[str] = []
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = docx_paragraph_text(child)
            if paragraph:
                blocks.append(paragraph)
        elif tag == "tbl":
            rows = []
            for row in child.findall("w:tr", DOCX_NS):
                cells = []
                for cell in row.findall("w:tc", DOCX_NS):
                    cells.append(" ".join(filter(None, (docx_paragraph_text(p) for p in cell.findall("w:p", DOCX_NS)))))
                rows.append(cells)
            if rows:
                blocks.append(rows_to_markdown(rows, heading="Word table"))
    return "\n\n".join(blocks)


def docx_paragraph_text(node: ET.Element) -> str:
    fragments = []
    for item in node.iter():
        tag = item.tag.rsplit("}", 1)[-1]
        if tag == "t" and item.text:
            fragments.append(item.text)
        elif tag in {"tab"}:
            fragments.append("\t")
        elif tag in {"br", "cr"}:
            fragments.append("\n")
    return "".join(fragments).strip()


def textutil_to_text(path: Path) -> str:
    textutil = shutil.which("textutil")
    if not textutil:
        raise RuntimeError("textutil is not installed")
    result = subprocess.run(
        [textutil, "-convert", "txt", "-stdout", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def xlsx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared_strings = parse_shared_strings(archive)
        sheet_map = parse_workbook_sheets(archive)
        blocks = []
        for sheet_name, sheet_path in sheet_map:
            if sheet_path not in archive.namelist():
                continue
            rows = parse_sheet_rows(archive.read(sheet_path), shared_strings)
            if rows:
                blocks.append(rows_to_markdown(rows, heading=sheet_name))
        return "\n\n".join(blocks)


def parse_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("x:si", XLSX_MAIN_NS):
        values.append("".join(node.text or "" for node in item.iter() if node.tag.rsplit("}", 1)[-1] == "t"))
    return values


def parse_workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: f"xl/{rel.attrib['Target']}".replace("xl//", "xl/")
        for rel in relationships.findall("r:Relationship", REL_NS)
    }
    sheets = []
    for sheet in workbook.findall("x:sheets/x:sheet", XLSX_MAIN_NS):
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rel_id or "", "")
        sheets.append((sheet.attrib.get("name", "Sheet"), target))
    return sheets


def parse_sheet_rows(xml_bytes: bytes, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(xml_bytes)
    rows = []
    for row in root.findall("x:sheetData/x:row", XLSX_MAIN_NS):
        row_values: dict[int, str] = {}
        for cell in row.findall("x:c", XLSX_MAIN_NS):
            ref = cell.attrib.get("r", "")
            col_index = xlsx_column_index(ref)
            cell_type = cell.attrib.get("t", "")
            value = ""
            if cell_type == "s":
                shared_index = cell.findtext("x:v", default="", namespaces=XLSX_MAIN_NS)
                value = shared_strings[int(shared_index)] if shared_index.isdigit() and int(shared_index) < len(shared_strings) else ""
            elif cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter() if node.tag.rsplit("}", 1)[-1] == "t")
            else:
                value = cell.findtext("x:v", default="", namespaces=XLSX_MAIN_NS)
            row_values[col_index] = value
        if row_values:
            width = max(row_values) + 1
            rows.append([row_values.get(index, "") for index in range(width)])
    return rows


def xlsx_column_index(reference: str) -> int:
    letters = "".join(ch for ch in reference if ch.isalpha()).upper()
    if not letters:
        return 0
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - 64)
    return max(index - 1, 0)


def pptx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name))
        blocks = []
        for idx, slide_name in enumerate(slide_names, start=1):
            root = ET.fromstring(archive.read(slide_name))
            text_runs = [node.text or "" for node in root.iter() if node.tag == PPTX_TEXT_TAG]
            slide_text = "\n".join(part.strip() for part in text_runs if part.strip())
            if slide_text:
                blocks.append(f"### Slide {idx}\n\n{slide_text}")
        return "\n\n".join(blocks)


def unsupported_stub(name: str, notes: str) -> str:
    return f"# {name}\n\n## Metadata\n- Notes: {notes}\n\n## LLM View\n(No normalized text available.)\n"
