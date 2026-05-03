from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import JSONResponse

from funnel_app import db as legacy_db

router = APIRouter()

MCP_PROTOCOL_VERSION = "2025-11-25"
TOOL_SCOPES = {
    "list_report_sections": "read",
    "read_report_section": "read",
    "preview_report_section": "read",
    "preview_report_completion": "read",
    "repair_completion_blockers": "read",
    "patch_report_section": "write_reports",
    "attach_sources_to_entries": "write_reports",
    "upload_document": "write_sources",
    "create_report_source": "write_sources",
    "finalize_report": "finalize_reports",
}


def bridge_from_request(request: Request):
    return request.app.state.bridge


def rpc_result(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def rpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return JSONResponse(payload, status_code=200)


def with_db(request: Request, operation):
    bridge = bridge_from_request(request)
    with bridge.open_db() as conn:
        return operation(conn)


def run_write(conn: sqlite3.Connection, operation):
    def wrapped():
        try:
            return operation()
        except sqlite3.Error:
            conn.rollback()
            raise

    return legacy_db.retry_busy(wrapped)


def decode_inline_file(arguments: dict[str, Any]) -> tuple[str | None, bytes | None, str]:
    file_name = str(arguments.get("file_name") or "").strip()
    content_b64 = arguments.get("file_content_base64")
    if not file_name and not content_b64:
        return None, None, ""
    if not file_name or not content_b64:
        raise ValueError("file_name and file_content_base64 are required together.")
    try:
        return file_name, base64.b64decode(str(content_b64), validate=True), str(arguments.get("file_mime_type") or "")
    except (binascii.Error, ValueError) as exc:
        raise ValueError("file_content_base64 must be valid base64.") from exc


def text_content(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


def tool_result(payload: Any) -> dict[str, Any]:
    return {
        "content": text_content(json.dumps(payload, ensure_ascii=False, indent=2)),
        "structuredContent": payload,
    }


def require_scope(request: Request, required_scope: str) -> None:
    session_payload = getattr(request.state, "session_payload", None)
    if session_payload is None or not getattr(session_payload, "required", False):
        return
    scopes = set(getattr(session_payload, "scopes", ()) or ())
    if "admin" in scopes or required_scope in scopes:
        return
    raise PermissionError(f"MCP scope required: {required_scope}")


def tool_defs() -> list[dict[str, Any]]:
    integer = {"type": "integer", "minimum": 1}
    string = {"type": "string"}
    return [
        {
            "name": "list_report_sections",
            "title": "List Report Sections",
            "description": "List modular section JSON summaries for a report.",
            "inputSchema": {"type": "object", "properties": {"report_id": integer}, "required": ["report_id"]},
        },
        {
            "name": "read_report_section",
            "title": "Read Report Section",
            "description": "Read one modular report section with entries, notes, sources, and section completion.",
            "inputSchema": {
                "type": "object",
                "properties": {"report_id": integer, "section_id": string},
                "required": ["report_id", "section_id"],
            },
        },
        {
            "name": "patch_report_section",
            "title": "Patch Report Section",
            "description": "Patch one report section. Requires report and section revisions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "report_id": integer,
                    "section_id": string,
                    "expected_report_revision": {"type": "integer"},
                    "expected_section_revision": {"type": "integer"},
                    "entries": {"type": "array", "items": {"type": "object"}},
                    "responses": {"type": "object"},
                    "metrics": {"type": "object"},
                    "field_sources": {"type": "object"},
                    "field_notes": {"type": "object"},
                    "field_exceptions": {"type": "object"},
                    "section_notes": {"type": "string"},
                    "section_sources": {"type": "object"},
                },
                "required": ["report_id", "section_id", "expected_report_revision", "expected_section_revision"],
            },
        },
        {
            "name": "preview_report_section",
            "title": "Preview Report Section",
            "description": "Preview a section patch without finalizing the report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "report_id": integer,
                    "section_id": string,
                    "expected_report_revision": {"type": "integer"},
                    "entries": {"type": "array", "items": {"type": "object"}},
                    "responses": {"type": "object"},
                    "metrics": {"type": "object"},
                    "field_sources": {"type": "object"},
                    "field_notes": {"type": "object"},
                    "field_exceptions": {"type": "object"},
                    "section_notes": {"type": "string"},
                    "section_sources": {"type": "object"},
                },
                "required": ["report_id", "section_id"],
            },
        },
        {
            "name": "preview_report_completion",
            "title": "Preview Report Completion",
            "description": "Run server-authoritative report completion preview.",
            "inputSchema": {
                "type": "object",
                "properties": {"report_id": integer, "payload": {"type": "object"}},
                "required": ["report_id", "payload"],
            },
        },
        {
            "name": "upload_document",
            "title": "Upload Document",
            "description": "Upload a company/report document using base64 content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "company_id": integer,
                    "report_id": integer,
                    "file_name": string,
                    "file_content_base64": string,
                    "file_mime_type": string,
                    "notes": string,
                },
                "required": ["company_id", "file_name", "file_content_base64"],
            },
        },
        {
            "name": "create_report_source",
            "title": "Create Report Source",
            "description": "Create a report source with optional base64 snapshot content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "report_id": integer,
                    "title": string,
                    "source_type": string,
                    "evidence_grade": string,
                    "confidence": string,
                    "url": string,
                    "citation": string,
                    "tags": string,
                    "notes": string,
                    "link_only_reason": string,
                    "snapshot_guidance_acknowledged": {"type": "boolean"},
                    "file_name": string,
                    "file_content_base64": string,
                    "file_mime_type": string,
                },
                "required": ["report_id", "title"],
            },
        },
        {
            "name": "attach_sources_to_entries",
            "title": "Attach Sources To Entries",
            "description": "Attach source contexts to fields in one section.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "report_id": integer,
                    "section_id": string,
                    "expected_report_revision": {"type": "integer"},
                    "expected_section_revision": {"type": "integer"},
                    "field_sources": {"type": "object"},
                    "section_sources": {"type": "object"},
                },
                "required": ["report_id", "section_id", "expected_report_revision", "expected_section_revision"],
            },
        },
        {
            "name": "repair_completion_blockers",
            "title": "Repair Completion Blockers",
            "description": "Return current completion blockers for repair planning.",
            "inputSchema": {"type": "object", "properties": {"report_id": integer}, "required": ["report_id"]},
        },
        {
            "name": "finalize_report",
            "title": "Finalize Report",
            "description": "Finalize a report after explicit approval. Server completion gates still apply.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "report_id": integer,
                    "expected_revision": {"type": "integer"},
                    "approved": {"type": "boolean"},
                    "result": string,
                },
                "required": ["report_id", "expected_revision", "approved"],
            },
        },
    ]


def prompt_defs() -> list[dict[str, Any]]:
    return [
        {"name": "complete_report_section", "title": "Complete Report Section", "description": "Complete one modular report section using existing sources."},
        {"name": "source_gap_analysis", "title": "Source Gap Analysis", "description": "Identify missing source evidence before filling a section."},
        {"name": "repair_section_blockers", "title": "Repair Section Blockers", "description": "Repair section completion blockers using the section completion object."},
        {"name": "summarize_upstream_handoff", "title": "Summarize Upstream Handoff", "description": "Summarize prior completed reports for this stage."},
        {"name": "final_report_review", "title": "Final Report Review", "description": "Review report-level completion before finalization."},
    ]


def resource_templates() -> list[dict[str, str]]:
    return [
        {"uriTemplate": "funnel://reports/{report_id}/outline", "name": "report_outline", "title": "Report Outline", "mimeType": "application/json"},
        {"uriTemplate": "funnel://reports/{report_id}/sections/{section_id}", "name": "report_section", "title": "Report Section", "mimeType": "application/json"},
        {"uriTemplate": "funnel://reports/{report_id}/completion", "name": "report_completion", "title": "Report Completion", "mimeType": "application/json"},
        {"uriTemplate": "funnel://reports/{report_id}/workflow", "name": "report_workflow", "title": "Report Workflow", "mimeType": "application/json"},
        {"uriTemplate": "funnel://reports/{report_id}/sources", "name": "report_sources", "title": "Report Sources", "mimeType": "application/json"},
        {"uriTemplate": "funnel://documents/{document_id}/normalized", "name": "normalized_document", "title": "Normalized Document", "mimeType": "text/plain"},
        {"uriTemplate": "funnel://templates/{template_id}/sections/{section_id}", "name": "template_section", "title": "Template Section", "mimeType": "application/json"},
    ]


def read_resource(request: Request, uri: str) -> dict[str, Any]:
    require_scope(request, "read")
    parts = uri.removeprefix("funnel://").split("/")
    if len(parts) >= 3 and parts[0] == "reports":
        report_id = int(parts[1])
        if parts[2] == "outline":
            payload = with_db(request, lambda conn: legacy_db.list_report_sections(conn, report_id))
            return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
        if parts[2] == "sections" and len(parts) >= 4:
            payload = with_db(request, lambda conn: legacy_db.get_report_section(conn, report_id, parts[3]))
            return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload["section"], ensure_ascii=False, indent=2)}
        if parts[2] in {"completion", "workflow", "sources"}:
            report = with_db(request, lambda conn: legacy_db.get_report(conn, report_id))
            if not report:
                raise KeyError("Report not found.")
            key = {"completion": "completion", "workflow": "workflow", "sources": "sources"}[parts[2]]
            return {"uri": uri, "mimeType": "application/json", "text": json.dumps(report.get(key), ensure_ascii=False, indent=2)}
    if len(parts) >= 3 and parts[0] == "documents" and parts[2] == "normalized":
        document_id = int(parts[1])

        def load(conn):
            document = legacy_db.get_document(conn, document_id)
            if not document:
                raise KeyError("Document not found.")
            if document.get("normalized_status") == legacy_db.DOCUMENT_STATUS_PENDING:
                raise ValueError("Normalized document is not ready yet.")
            path = Path(document.get("normalized_text_path") or "")
            if not path.exists():
                raise KeyError("Normalized document not found.")
            return path.read_text(encoding="utf-8")

        return {"uri": uri, "mimeType": "text/plain", "text": with_db(request, load)}
    if len(parts) >= 4 and parts[0] == "templates" and parts[2] == "sections":
        template_id = int(parts[1])
        section_id = parts[3]

        def load(conn):
            template = legacy_db.get_template(conn, template_id)
            if not template:
                raise KeyError("Template not found.")
            legacy_db.upsert_template_section_modules(conn, template)
            conn.commit()
            row = conn.execute(
                "SELECT module_json FROM template_section_modules WHERE template_id = ? AND section_id = ?",
                (template_id, section_id),
            ).fetchone()
            if not row:
                raise KeyError("Template section not found.")
            return legacy_db.load_json(row["module_json"], {})

        payload = with_db(request, load)
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    raise KeyError("Resource not found.")


def call_tool(request: Request, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name in TOOL_SCOPES:
        require_scope(request, TOOL_SCOPES[name])
    mutating_tools = {
        "patch_report_section",
        "attach_sources_to_entries",
        "upload_document",
        "create_report_source",
        "finalize_report",
    }
    if name in mutating_tools and bool(getattr(request.state, "write_freeze_state", {}).get("write_frozen")):
        raise ValueError(str(request.state.write_freeze_state.get("message") or "Writes are temporarily frozen."))
    if name == "list_report_sections":
        return tool_result(with_db(request, lambda conn: legacy_db.list_report_sections(conn, int(arguments["report_id"]))))
    if name == "read_report_section":
        return tool_result(
            with_db(
                request,
                lambda conn: legacy_db.get_report_section(conn, int(arguments["report_id"]), str(arguments["section_id"])),
            )
        )
    if name in {"patch_report_section", "attach_sources_to_entries"}:
        payload = dict(arguments)
        report_id = int(payload.pop("report_id"))
        section_id = str(payload.pop("section_id"))
        return tool_result(
            with_db(
                request,
                lambda conn: run_write(conn, lambda: legacy_db.update_report_section(conn, report_id, section_id, payload)),
            )
        )
    if name == "preview_report_section":
        payload = dict(arguments)
        report_id = int(payload.pop("report_id"))
        section_id = str(payload.pop("section_id"))
        return tool_result(with_db(request, lambda conn: legacy_db.preview_report_section(conn, report_id, section_id, payload)))
    if name == "preview_report_completion":
        return tool_result(
            with_db(
                request,
                lambda conn: legacy_db.preview_report_completion(conn, int(arguments["report_id"]), dict(arguments.get("payload") or {})),
            )
        )
    if name == "upload_document":
        file_name, content, mime_type = decode_inline_file(arguments)
        if content is None or file_name is None:
            raise ValueError("file content is required.")
        return tool_result(
            with_db(
                request,
                lambda conn: {
                    "documents": [
                        run_write(
                            conn,
                            lambda: legacy_db.save_document(
                                conn,
                                bridge_from_request(request).settings.upload_root,
                                int(arguments["company_id"]),
                                file_name,
                                content,
                                report_id=int(arguments["report_id"]) if arguments.get("report_id") else None,
                                notes=str(arguments.get("notes") or ""),
                                mime_type=mime_type,
                            ),
                        )
                    ]
                },
            )
        )
    if name == "create_report_source":
        file_name, content, mime_type = decode_inline_file(arguments)
        payload = dict(arguments)
        return tool_result(
            with_db(
                request,
                lambda conn: {
                    "source": run_write(
                        conn,
                        lambda: legacy_db.save_report_source(
                            conn,
                            bridge_from_request(request).settings.upload_root,
                            int(payload["report_id"]),
                            payload,
                            file_name=file_name,
                            file_content=content,
                            file_mime_type=mime_type,
                        ),
                    )
                },
            )
        )
    if name == "repair_completion_blockers":
        report = with_db(request, lambda conn: legacy_db.get_report(conn, int(arguments["report_id"])))
        if not report:
            raise KeyError("Report not found.")
        completion = report.get("completion") or {}
        return tool_result(
            {
                "report_id": int(arguments["report_id"]),
                "completion": completion,
                "blockers": {
                    "missing_fields": completion.get("missing_fields", []),
                    "missing_source_links": completion.get("missing_source_links", []),
                    "blocked_source_links": completion.get("blocked_source_links", []),
                    "missing_required_notes": completion.get("missing_required_notes", []),
                    "exception_missing_notes": completion.get("exception_missing_notes", []),
                    "decision_requirements": completion.get("decision_requirements", []),
                },
            }
        )
    if name == "finalize_report":
        if not bool(arguments.get("approved")):
            raise ValueError("finalize_report requires approved=true.")
        payload: dict[str, Any] = {"expected_revision": int(arguments["expected_revision"]), "finalize": True}
        if arguments.get("result"):
            payload["result"] = str(arguments["result"])
        return tool_result(
            with_db(
                request,
                lambda conn: {
                    "report": run_write(conn, lambda: legacy_db.update_report(conn, int(arguments["report_id"]), payload))
                },
            )
        )
    raise KeyError("Tool not found.")


def prompt_payload(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    report_id = arguments.get("report_id", "{report_id}")
    section_id = arguments.get("section_id", "{section_id}")
    prompts = {
        "complete_report_section": f"Read funnel://reports/{report_id}/sections/{section_id}, use existing sources first, patch only that section, preview it, save it, then re-read it and verify the section revision changed.",
        "source_gap_analysis": f"Read funnel://reports/{report_id}/sources and funnel://reports/{report_id}/sections/{section_id}. List missing or weak evidence before any report patch.",
        "repair_section_blockers": f"Read funnel://reports/{report_id}/sections/{section_id}. Repair only the blockers in the section completion object, preserving existing values.",
        "summarize_upstream_handoff": f"Read funnel://reports/{report_id}/workflow and summarize only prior completed reports relevant to the current stage.",
        "final_report_review": f"Read funnel://reports/{report_id}/completion. Do not finalize until every blocker is resolved and the user has approved finalization.",
    }
    if name not in prompts:
        raise KeyError("Prompt not found.")
    return {
        "description": next(item["description"] for item in prompt_defs() if item["name"] == name),
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": prompts[name],
                },
            }
        ],
    }


@router.get("/mcp")
def get_mcp() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {"name": "stock-picking-funnel", "version": "0.1.0"},
        "capabilities": {"resources": {}, "tools": {}, "prompts": {}},
    }


@router.post("/mcp")
async def post_mcp(request: Request):
    body = await request.body()
    try:
        message = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError:
        return rpc_error(None, -32700, "Parse error")
    request_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params") or {}
    try:
        if method == "initialize":
            return rpc_result(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"resources": {}, "tools": {}, "prompts": {}},
                    "serverInfo": {"name": "stock-picking-funnel", "version": "0.1.0"},
                },
            )
        if method == "notifications/initialized":
            return JSONResponse(status_code=202, content={})
        if method == "tools/list":
            return rpc_result(request_id, {"tools": tool_defs()})
        if method == "tools/call":
            return rpc_result(request_id, call_tool(request, str(params.get("name") or ""), dict(params.get("arguments") or {})))
        if method == "resources/templates/list":
            return rpc_result(request_id, {"resourceTemplates": resource_templates()})
        if method == "resources/list":
            return rpc_result(request_id, {"resources": []})
        if method == "resources/read":
            return rpc_result(request_id, {"contents": [read_resource(request, str(params.get("uri") or ""))]})
        if method == "prompts/list":
            return rpc_result(request_id, {"prompts": prompt_defs()})
        if method == "prompts/get":
            return rpc_result(request_id, prompt_payload(str(params.get("name") or ""), dict(params.get("arguments") or {})))
    except KeyError as exc:
        return rpc_error(request_id, -32002, str(exc).strip("'"))
    except ValueError as exc:
        return rpc_error(request_id, -32602, str(exc))
    except PermissionError as exc:
        return rpc_error(request_id, -32003, str(exc))
    except legacy_db.ReportRevisionConflict as exc:
        return rpc_error(request_id, -32001, str(exc), {"current_revision": exc.current_revision, "updated_at": exc.updated_at})
    except legacy_db.ReportCompletionBlocked as exc:
        return rpc_error(request_id, -32000, str(exc), {"completion": exc.completion})
    except Exception as exc:
        return rpc_error(request_id, -32603, str(exc))
    return rpc_error(request_id, -32601, "Method not found")
