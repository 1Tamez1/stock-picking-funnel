from __future__ import annotations

import base64
import binascii
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import db
from .runtime import AppContext, AppRuntime


class RequestBodyError(Exception):
    status = HTTPStatus.BAD_REQUEST


class MissingContentLength(RequestBodyError):
    status = HTTPStatus.LENGTH_REQUIRED


class InvalidContentLength(RequestBodyError):
    status = HTTPStatus.BAD_REQUEST


class RequestBodyTooLarge(RequestBodyError):
    status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class FunnelServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], runtime: AppRuntime):
        self.runtime = runtime
        super().__init__(server_address, FunnelHandler)

    def server_close(self) -> None:
        self.runtime.stop()
        super().server_close()


class FunnelHandler(BaseHTTPRequestHandler):
    server_version = "StockFunnel/0.2"

    @property
    def runtime(self) -> AppRuntime:
        return self.server.runtime  # type: ignore[attr-defined]

    @property
    def context(self) -> AppContext:
        return self.runtime.context

    def prepare_request_context(self) -> None:
        if getattr(self, "request_id", None):
            return
        self.request_id = uuid.uuid4().hex
        self.request_started_at = time.monotonic()

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("FUNNEL_QUIET") == "1":
            return
        super().log_message(format, *args)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        if os.environ.get("FUNNEL_QUIET") == "1":
            return
        duration_ms = int((time.monotonic() - getattr(self, "request_started_at", time.monotonic())) * 1000)
        self.log_message(
            '"%s %s" %s %s %dms req=%s instance=%s',
            getattr(self, "command", "-"),
            getattr(self, "path", "-"),
            str(code),
            str(size),
            duration_ms,
            getattr(self, "request_id", "-"),
            self.runtime.instance_id,
        )

    def begin_response(
        self,
        status: int,
        *,
        content_type: str,
        content_length: int,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.prepare_request_context()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("X-Funnel-Instance-Id", self.runtime.instance_id)
        self.send_header("X-Funnel-Request-Id", self.request_id)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.begin_response(status, content_type="application/json; charset=utf-8", content_length=len(body))
        self.wfile.write(body)

    def send_error_json(
        self,
        message: str,
        status: int = 400,
        *,
        code: str = "bad_request",
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {"error": message, "code": code, "request_id": getattr(self, "request_id", "")}
        if extra:
            payload.update(extra)
        self.send_json(payload, status)

    def request_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise MissingContentLength("Content-Length header is required.")
        try:
            length = int(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidContentLength("Content-Length header must be a non-negative integer.") from exc
        if length < 0:
            raise InvalidContentLength("Content-Length header must be a non-negative integer.")
        if length > self.context.max_upload_bytes:
            raise RequestBodyTooLarge(f"Request body exceeds the {self.context.max_upload_bytes} byte limit.")
        return length

    def read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length in (None, "", "0"):
            return {}
        length = self.request_length()
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    @contextmanager
    def open_db(self):
        conn = db.connect(self.context.database)
        try:
            yield conn
        finally:
            conn.close()

    def run_write(self, conn: sqlite3.Connection, operation):
        def wrapped():
            try:
                return operation()
            except sqlite3.Error:
                conn.rollback()
                raise

        return db.retry_busy(wrapped)

    def parse_multipart(self) -> dict[str, Any]:
        length = self.request_length()
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        fields: dict[str, Any] = {}
        files = []
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                files.append(
                    {
                        "field": name,
                        "filename": filename,
                        "content": payload,
                        "mime_type": part.get_content_type(),
                        "origin": "uploaded_file",
                    }
                )
            elif name:
                fields[name] = payload.decode(part.get_content_charset() or "utf-8")
        fields["files"] = files
        return fields

    def content_type(self) -> str:
        return self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()

    def is_multipart(self) -> bool:
        return self.content_type() == "multipart/form-data"

    def inline_file_from_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        file_name = str(payload.get("file_name") or "").strip()
        content_b64 = payload.get("file_content_base64")
        if not file_name and not content_b64:
            return None
        if not file_name or not content_b64:
            raise ValueError("file_name and file_content_base64 are required together.")
        try:
            content = base64.b64decode(str(content_b64), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("file_content_base64 must be valid base64.") from exc
        return {
            "field": "file",
            "filename": file_name,
            "content": content,
            "mime_type": str(payload.get("file_mime_type") or "").strip(),
            "origin": "inline_snapshot",
        }

    def read_upload_payload(self) -> dict[str, Any]:
        payload = self.parse_multipart() if self.is_multipart() else self.read_json()
        payload = dict(payload)
        files = list(payload.get("files") or [])
        inline_file = self.inline_file_from_payload(payload)
        if inline_file:
            files.append(inline_file)
        payload["files"] = files
        return payload

    def do_GET(self) -> None:
        self.prepare_request_context()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path.startswith("/api/"):
            self.handle_get_api(path, query)
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        self.prepare_request_context()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not path.startswith("/api/"):
            self.send_error_json("Not found.", HTTPStatus.NOT_FOUND, code="not_found")
            return
        self.handle_write_api("POST", path)

    def do_PATCH(self) -> None:
        self.prepare_request_context()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not path.startswith("/api/"):
            self.send_error_json("Not found.", HTTPStatus.NOT_FOUND, code="not_found")
            return
        self.handle_write_api("PATCH", path)

    def do_DELETE(self) -> None:
        self.prepare_request_context()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not path.startswith("/api/"):
            self.send_error_json("Not found.", HTTPStatus.NOT_FOUND, code="not_found")
            return
        self.handle_write_api("DELETE", path)

    def health_payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        return {
            "ok": True,
            "instance_id": self.runtime.instance_id,
            "started_at": self.runtime.started_at,
            "pid": os.getpid(),
            "db_path": str(self.context.database.resolve()),
            "upload_dir": str(self.context.uploads.resolve()),
            "schema_version": db.database_schema_version(conn),
            "worker": self.runtime.worker_health(conn),
        }

    def handle_get_api(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            with self.open_db() as conn:
                if path == "/api/health":
                    self.send_json(self.health_payload(conn))
                    return
                if path == "/api/bootstrap":
                    self.send_json(
                        {
                            "dashboard": db.dashboard(conn),
                            "settings_summary": db.settings_summary(conn),
                            "stages": db.list_stages(conn),
                            "buckets": db.BUCKETS,
                            "report_actions": db.REPORT_ACTIONS,
                        }
                    )
                    return
                if path == "/api/stages":
                    self.send_json({"stages": db.list_stages(conn)})
                    return
                if path == "/api/companies":
                    bucket = first(query, "bucket")
                    stage_id = first(query, "stage_id")
                    search = first(query, "search")
                    order = first(query, "order")
                    page = int(first(query, "page") or "1")
                    per_page = int(first(query, "per_page") or "500")
                    self.send_json(
                        {
                            "companies": db.list_companies(
                                conn,
                                bucket=bucket,
                                stage_id=int(stage_id) if stage_id else None,
                                search=search,
                                order=order,
                                page=page,
                                per_page=per_page,
                            ),
                            "total": db.count_companies(
                                conn,
                                bucket=bucket,
                                stage_id=int(stage_id) if stage_id else None,
                                search=search,
                            ),
                            "page": page,
                            "per_page": per_page,
                        }
                    )
                    return
                if path.startswith("/api/companies/"):
                    company_id = int(path.split("/")[-1])
                    company = db.get_company(conn, company_id)
                    if not company:
                        self.send_error_json("Company not found.", HTTPStatus.NOT_FOUND, code="not_found")
                    else:
                        self.send_json({"company": company})
                    return
                if path == "/api/templates":
                    self.send_json({"templates": db.list_templates(conn)})
                    return
                if path.startswith("/api/templates/"):
                    template_id = int(path.split("/")[-1])
                    template = db.get_template(conn, template_id)
                    if not template:
                        self.send_error_json("Template not found.", HTTPStatus.NOT_FOUND, code="not_found")
                    else:
                        self.send_json({"template": template})
                    return
                if path == "/api/reports":
                    stage_id = first(query, "stage_id")
                    result = first(query, "result")
                    search = first(query, "search")
                    order = first(query, "order")
                    include_drafts_raw = first(query, "include_drafts")
                    include_drafts = (
                        db.parse_boolean_flag(include_drafts_raw, field_name="include_drafts")
                        if include_drafts_raw is not None
                        else False
                    )
                    page = int(first(query, "page") or "1")
                    per_page = int(first(query, "per_page") or "50")
                    self.send_json(
                        {
                            "reports": db.list_report_summaries(
                                conn,
                                stage_id=int(stage_id) if stage_id else None,
                                result=result,
                                search=search,
                                include_drafts=include_drafts,
                                order=order or "completed_desc",
                                page=page,
                                per_page=per_page,
                                include_company=True,
                                include_completed_at=True,
                            ),
                            "total": db.count_reports(
                                conn,
                                stage_id=int(stage_id) if stage_id else None,
                                result=result,
                                search=search,
                                include_drafts=include_drafts,
                            ),
                            "page": page,
                            "per_page": per_page,
                        }
                    )
                    return
                if path.startswith("/api/reports/"):
                    report_id = int(path.split("/")[-1])
                    report = db.get_report(conn, report_id)
                    if not report:
                        self.send_error_json("Report not found.", HTTPStatus.NOT_FOUND, code="not_found")
                    else:
                        self.send_json({"report": report})
                    return
                if path == "/api/monitoring":
                    self.send_json({"rules": db.list_monitoring_rules(conn, bucket="monitoring")})
                    return
                if path.startswith("/api/documents/") and path.endswith("/status"):
                    document_id = int(path.split("/")[-2])
                    document = db.document_status_record(conn, document_id)
                    if not document:
                        self.send_error_json("Document not found.", HTTPStatus.NOT_FOUND, code="not_found")
                    else:
                        self.send_json({"document": document})
                    return
                if path.startswith("/api/documents/") and path.endswith("/normalized"):
                    document_id = int(path.split("/")[-2])
                    self.serve_normalized_document(conn, document_id)
                    return
                if path.startswith("/api/documents/") and path.endswith("/download"):
                    document_id = int(path.split("/")[-2])
                    self.serve_document(conn, document_id)
                    return
                self.send_error_json("Not found.", HTTPStatus.NOT_FOUND, code="not_found")
        except Exception as exc:
            self.handle_api_exception(exc)

    def handle_write_api(self, method: str, path: str) -> None:
        try:
            with self.open_db() as conn:
                if method == "POST" and path == "/api/companies":
                    payload = self.read_json()
                    company = self.run_write(conn, lambda: db.create_company(conn, payload))
                    self.send_json({"company": company}, HTTPStatus.CREATED)
                    return
                if method == "PATCH" and path.startswith("/api/companies/"):
                    company_id = int(path.split("/")[-1])
                    payload = self.read_json()
                    company = self.run_write(conn, lambda: db.update_company(conn, company_id, payload))
                    self.send_json({"company": company})
                    return
                if method == "POST" and path == "/api/templates":
                    payload = self.read_json()
                    template = self.run_write(conn, lambda: db.save_template(conn, payload))
                    self.send_json({"template": template}, HTTPStatus.CREATED)
                    return
                if method == "PATCH" and path.startswith("/api/templates/"):
                    template_id = int(path.split("/")[-1])
                    payload = self.read_json()
                    payload["id"] = template_id
                    template = self.run_write(conn, lambda: db.save_template(conn, payload))
                    self.send_json({"template": template})
                    return
                if method == "DELETE" and path.startswith("/api/templates/"):
                    template_id = int(path.split("/")[-1])
                    self.run_write(conn, lambda: db.delete_template(conn, template_id))
                    self.send_json({"ok": True})
                    return
                if method == "POST" and path == "/api/reports":
                    payload = self.read_json()
                    report = self.run_write(conn, lambda: db.create_report(conn, payload))
                    self.send_json({"report": report}, HTTPStatus.CREATED)
                    return
                if method == "POST" and path.startswith("/api/reports/") and path.endswith("/preview"):
                    report_id = int(path.split("/")[-2])
                    payload = self.read_json()
                    if "expected_revision" not in payload:
                        self.send_error_json(
                            "expected_revision is required.",
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                            code="validation_error",
                        )
                        return
                    preview = db.preview_report_completion(conn, report_id, payload)
                    self.send_json(preview)
                    return
                if method == "PATCH" and path.startswith("/api/reports/"):
                    report_id = int(path.split("/")[-1])
                    payload = self.read_json()
                    if "expected_revision" not in payload:
                        self.send_error_json(
                            "expected_revision is required.",
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                            code="validation_error",
                        )
                        return
                    payload.setdefault("finalize", False)
                    report = self.run_write(conn, lambda: db.update_report(conn, report_id, payload))
                    self.send_json({"report": report})
                    return
                if method == "DELETE" and path.startswith("/api/reports/"):
                    report_id = int(path.split("/")[-1])
                    company = self.run_write(conn, lambda: db.delete_report(conn, report_id))
                    self.send_json({"ok": True, "company": company})
                    return
                if method == "POST" and path == "/api/documents":
                    parts = self.read_upload_payload()
                    files = parts.get("files") or []
                    if not files:
                        self.send_error_json(
                            "A file upload is required.",
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                            code="validation_error",
                        )
                        return
                    saved = []
                    for item in files:
                        saved.append(
                            self.run_write(
                                conn,
                                lambda item=item: db.save_document(
                                    conn,
                                    self.context.uploads,
                                    int(parts["company_id"]),
                                    item["filename"],
                                    item["content"],
                                    report_id=int(parts["report_id"]) if parts.get("report_id") else None,
                                    notes=parts.get("notes", ""),
                                    mime_type=item.get("mime_type", ""),
                                ),
                            )
                        )
                    self.send_json({"documents": saved}, HTTPStatus.CREATED)
                    return
                if method == "POST" and path == "/api/report-sources":
                    parts = self.read_upload_payload()
                    files = parts.get("files") or []
                    first_file = files[0] if files else None
                    source = self.run_write(
                        conn,
                        lambda: db.save_report_source(
                            conn,
                            self.context.uploads,
                            int(parts["report_id"]) if parts.get("report_id") else None,
                            parts,
                            file_name=first_file["filename"] if first_file else None,
                            file_content=first_file["content"] if first_file else None,
                            file_mime_type=first_file.get("mime_type", "") if first_file else "",
                            file_origin=first_file.get("origin", "") if first_file else "",
                        ),
                    )
                    self.send_json({"source": source}, HTTPStatus.CREATED)
                    return
                if method == "PATCH" and path.startswith("/api/report-sources/"):
                    source_id = int(path.split("/")[-1])
                    parts = self.read_upload_payload()
                    files = parts.get("files") or []
                    first_file = files[0] if files else None
                    parts["id"] = source_id
                    source = self.run_write(
                        conn,
                        lambda: db.save_report_source(
                            conn,
                            self.context.uploads,
                            int(parts["report_id"]) if parts.get("report_id") else None,
                            parts,
                            file_name=first_file["filename"] if first_file else None,
                            file_content=first_file["content"] if first_file else None,
                            file_mime_type=first_file.get("mime_type", "") if first_file else "",
                            file_origin=first_file.get("origin", "") if first_file else "",
                        ),
                    )
                    self.send_json({"source": source})
                    return
                if method == "DELETE" and path.startswith("/api/report-sources/"):
                    source_id = int(path.split("/")[-1])
                    self.run_write(conn, lambda: db.delete_report_source(conn, source_id))
                    self.send_json({"ok": True})
                    return
                if method == "POST" and path == "/api/monitoring-rules":
                    payload = self.read_json()
                    rule = self.run_write(conn, lambda: db.save_monitoring_rule(conn, payload))
                    self.send_json({"rule": rule}, HTTPStatus.CREATED)
                    return
                if method == "PATCH" and path.startswith("/api/monitoring-rules/"):
                    rule_id = int(path.split("/")[-1])
                    payload = self.read_json()
                    payload["id"] = rule_id
                    rule = self.run_write(conn, lambda: db.save_monitoring_rule(conn, payload))
                    self.send_json({"rule": rule})
                    return
                self.send_error_json("Not found.", HTTPStatus.NOT_FOUND, code="not_found")
        except Exception as exc:
            self.handle_api_exception(exc)

    def handle_api_exception(self, exc: Exception) -> None:
        if isinstance(exc, RequestBodyError):
            code = exc.__class__.__name__.lower()
            self.send_error_json(str(exc), exc.status, code=code)
            return
        if isinstance(exc, db.ReportRevisionConflict):
            self.send_json(
                {
                    "error": str(exc),
                    "code": "report_revision_conflict",
                    "request_id": getattr(self, "request_id", ""),
                    "current_revision": exc.current_revision,
                    "updated_at": exc.updated_at,
                },
                HTTPStatus.CONFLICT,
            )
            return
        if isinstance(exc, db.ReportCompletionBlocked):
            self.send_json(
                {
                    "error": str(exc),
                    "code": "report_completion_blocked",
                    "request_id": getattr(self, "request_id", ""),
                    "completion": exc.completion,
                },
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return
        if isinstance(exc, KeyError):
            message = str(exc).strip("'")
            status = HTTPStatus.NOT_FOUND if "not found" in message.lower() else HTTPStatus.UNPROCESSABLE_ENTITY
            code = "not_found" if status == HTTPStatus.NOT_FOUND else "validation_error"
            self.send_error_json(message, status, code=code)
            return
        if isinstance(exc, ValueError):
            self.send_error_json(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY, code="validation_error")
            return
        if isinstance(exc, sqlite3.IntegrityError):
            self.send_error_json(str(exc), HTTPStatus.CONFLICT, code="database_conflict")
            return
        if isinstance(exc, sqlite3.Error) and db.transient_sqlite_error(exc):
            self.send_error_json(
                "Database is busy. Retry the request.",
                HTTPStatus.CONFLICT,
                code="database_busy",
            )
            return
        self.send_error_json("Internal server error.", HTTPStatus.INTERNAL_SERVER_ERROR, code="internal_error")

    def serve_document(self, conn: sqlite3.Connection, document_id: int) -> None:
        document = db.get_document(conn, document_id)
        if not document:
            self.send_error_json("Document not found.", HTTPStatus.NOT_FOUND, code="not_found")
            return
        path = Path(document["storage_path"])
        if not path.exists():
            self.send_error_json("Document file is missing.", HTTPStatus.NOT_FOUND, code="not_found")
            return
        body = path.read_bytes()
        self.begin_response(
            HTTPStatus.OK,
            content_type=document["mime_type"] or "application/octet-stream",
            content_length=len(body),
            extra_headers={
                "Content-Disposition": f'attachment; filename="{document["original_name"]}"',
            },
        )
        self.wfile.write(body)

    def serve_normalized_document(self, conn: sqlite3.Connection, document_id: int) -> None:
        document = db.get_document(conn, document_id)
        if not document:
            self.send_error_json("Document not found.", HTTPStatus.NOT_FOUND, code="not_found")
            return
        normalized_path = Path(document.get("normalized_text_path") or "")
        if document.get("normalized_status") == db.DOCUMENT_STATUS_PENDING or not normalized_path.exists():
            self.send_error_json(
                "Normalized document is not ready yet.",
                HTTPStatus.CONFLICT,
                code="document_pending",
            )
            return
        body = normalized_path.read_bytes()
        filename = f"{Path(document['original_name']).stem}-llm.txt"
        self.begin_response(
            HTTPStatus.OK,
            content_type="text/plain; charset=utf-8",
            content_length=len(body),
            extra_headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
        self.wfile.write(body)

    def serve_static(self, path: str) -> None:
        if path == "/":
            target = self.context.static_root / "index.html"
        else:
            target = (self.context.static_root / path.lstrip("/")).resolve()
        if not str(target).startswith(str(self.context.static_root.resolve())) or not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = "text/html; charset=utf-8"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".png":
            content_type = "image/png"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def build_server(
    host: str = "127.0.0.1",
    port: int = 8011,
    context: AppContext | None = None,
    *,
    auto_confirm_seed: bool = False,
):
    runtime = AppRuntime(context or AppContext())
    runtime.initialize(auto_confirm_seed=auto_confirm_seed)
    return FunnelServer((host, port), runtime)


def main() -> None:
    host = os.environ.get("FUNNEL_HOST", "127.0.0.1")
    port = int(os.environ.get("FUNNEL_PORT", "8011"))
    server = build_server(host, port)
    print(f"Stock Picking Funnel running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
