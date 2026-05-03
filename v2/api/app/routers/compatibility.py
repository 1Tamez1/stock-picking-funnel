from __future__ import annotations

import base64
import binascii
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

V1_ROOT = Path(__file__).resolve().parents[5]
if str(V1_ROOT) not in sys.path:
    sys.path.insert(0, str(V1_ROOT))

from fastapi import APIRouter
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi import UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from funnel_app import db as legacy_db
from app.storage import storage_key_from_path
from app.storage import StorageResolution

router = APIRouter()


def bridge_from_request(request: Request):
    return request.app.state.bridge


def service_from_request(request: Request):
    return request.app.state.service


def auth_service_from_request(request: Request):
    return request.app.state.auth_service


def storage_from_request(request: Request):
    return request.app.state.storage


def response_headers(request: Request) -> dict[str, str]:
    bridge = bridge_from_request(request)
    return {
        "X-Funnel-Instance-Id": bridge.instance_id,
        "X-Funnel-Request-Id": bridge.request_id(),
    }


def json_response(
    request: Request,
    payload: Any,
    status_code: int = 200,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    headers = response_headers(request)
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(payload, status_code=status_code, headers=headers)


def api_error(request: Request, message: str, status_code: int, code: str, **extra: Any) -> JSONResponse:
    payload = {"error": message, "code": code, "request_id": response_headers(request)["X-Funnel-Request-Id"], **extra}
    headers = {
        "X-Funnel-Instance-Id": request.app.state.bridge.instance_id,
        "X-Funnel-Request-Id": payload["request_id"],
    }
    return JSONResponse(payload, status_code=status_code, headers=headers)


def apply_storage_resolution_headers(
    request: Request,
    response: Response,
    *,
    category: str,
    result,
    resolution: StorageResolution,
    detail_suffix: str = "",
) -> Response:
    response.headers["X-Funnel-Storage-Fallback"] = "1" if resolution.used_local_fallback else "0"
    response.headers["X-Funnel-Storage-Artifact"] = ""
    if not resolution.used_local_fallback:
        return response
    service = service_from_request(request)
    request_key = service.request_key(request, {"storage_category": category})
    artifact_path = service.shadow.record_fallback_event(
        category=f"{category}.storage",
        request_key=request_key,
        policy=result.policy,
        reason="storage_remote_missing",
        primary_backend="s3_compatible",
        detail=resolution.detail or detail_suffix or "Remote object missing; local fallback served.",
        artifact_path=result.artifact_path,
    )
    response.headers["X-Funnel-Storage-Artifact"] = str(artifact_path)
    return response


async def read_json_payload(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def inline_file_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
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
        "filename": file_name,
        "content": content,
        "mime_type": str(payload.get("file_mime_type") or "").strip(),
    }


async def read_upload_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        payload: dict[str, Any] = {}
        files: list[dict[str, Any]] = []
        for key, value in form.multi_items():
            if isinstance(value, (UploadFile, StarletteUploadFile)):
                files.append(
                    {
                        "field": key,
                        "filename": value.filename or "upload.bin",
                        "content": await value.read(),
                        "mime_type": value.content_type or "",
                    }
                )
                await value.close()
                continue
            payload[key] = value
        payload["files"] = files
        return payload
    payload = await read_json_payload(request)
    payload = dict(payload)
    files = list(payload.get("files") or [])
    inline = inline_file_from_payload(payload)
    if inline:
        files.append(inline)
    payload["files"] = files
    return payload


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def run_write(conn: sqlite3.Connection, operation):
    def wrapped():
        try:
            return operation()
        except sqlite3.Error:
            conn.rollback()
            raise

    return legacy_db.retry_busy(wrapped)


def with_db(bridge, operation):
    with bridge.open_db() as conn:
        return operation(conn)


def handle_exception(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, legacy_db.ReportRevisionConflict):
        return api_error(
            request,
            str(exc),
            409,
            "report_revision_conflict",
            current_revision=exc.current_revision,
            updated_at=exc.updated_at,
        )
    if isinstance(exc, legacy_db.ReportCompletionBlocked):
        return api_error(request, str(exc), 422, "report_completion_blocked", completion=exc.completion)
    if isinstance(exc, KeyError):
        message = str(exc).strip("'")
        status = 404 if "not found" in message.lower() else 422
        code = "not_found" if status == 404 else "validation_error"
        return api_error(request, message, status, code)
    if isinstance(exc, ValueError):
        return api_error(request, str(exc), 422, "validation_error")
    if isinstance(exc, sqlite3.IntegrityError):
        return api_error(request, str(exc), 409, "database_conflict")
    if isinstance(exc, sqlite3.Error) and legacy_db.transient_sqlite_error(exc):
        return api_error(request, "Database is busy. Retry the request.", 409, "database_busy")
    return api_error(request, "Internal server error.", 500, "internal_error")


@router.get("/api/health")
def get_health(request: Request):
    bridge = bridge_from_request(request)
    with bridge.open_db() as conn:
        return json_response(request, bridge.health_payload(conn))


@router.get("/api/health/runtime")
def get_runtime_health(request: Request):
    bridge = bridge_from_request(request)
    with bridge.open_db() as conn:
        return json_response(request, bridge.runtime_health_payload(conn))


@router.get("/api/session")
def get_session(request: Request):
    payload = request.state.session_payload.as_dict()
    return json_response(request, payload)


@router.post("/api/session/login")
async def post_session_login(request: Request):
    auth = auth_service_from_request(request)
    payload = await read_json_payload(request)
    try:
        token, body = auth.login(
            email=str(payload.get("email") or ""),
            password=str(payload.get("password") or ""),
            request=request,
        )
        response = json_response(request, body, status_code=201)
        response.set_cookie(
            key=request.app.state.settings.session_cookie_name,
            value=token,
            httponly=True,
            secure=bool(request.app.state.settings.session_secure),
            samesite="lax",
            max_age=int(request.app.state.settings.session_ttl_seconds),
            path="/",
        )
        return response
    except Exception as exc:
        if isinstance(exc, ValueError):
            return api_error(request, str(exc), 401, "invalid_credentials")
        return handle_exception(request, exc)


@router.post("/api/session/logout")
def post_session_logout(request: Request):
    auth = auth_service_from_request(request)
    body = auth.logout(request)
    response = json_response(request, body)
    response.delete_cookie(key=request.app.state.settings.session_cookie_name, path="/")
    return response


@router.get("/api/bootstrap")
def get_bootstrap(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    result = service_from_request(request).execute_read(
        request,
        "bootstrap",
        legacy_loader=lambda: with_db(bridge, bridge.bootstrap_payload),
        postgres_loader=lambda _request_key: service.postgres.bootstrap(),
    )
    return json_response(request, result.payload, extra_headers=result.headers)


@router.get("/api/stages")
def get_stages(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    result = service_from_request(request).execute_read(
        request,
        "stages",
        legacy_loader=lambda: with_db(bridge, lambda conn: {"stages": legacy_db.list_stages(conn)}),
        postgres_loader=lambda _request_key: service.postgres.stages(),
    )
    return json_response(request, result.payload, extra_headers=result.headers)


@router.get("/api/companies")
def get_companies(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    query = dict(request.query_params.multi_items())
    bucket = query.get("bucket")
    stage_id = query.get("stage_id")
    search = query.get("search")
    order = query.get("order")
    page = int(query.get("page") or "1")
    per_page = int(query.get("per_page") or "500")
    result = service_from_request(request).execute_read(
        request,
        "companies.list",
        extra={"bucket": bucket, "stage_id": stage_id, "search": search, "order": order, "page": page, "per_page": per_page},
        legacy_loader=lambda: with_db(
            bridge,
            lambda conn: {
                "companies": legacy_db.list_companies(
                    conn,
                    bucket=bucket,
                    stage_id=int(stage_id) if stage_id else None,
                    search=search,
                    order=order,
                    page=page,
                    per_page=per_page,
                ),
                "total": legacy_db.count_companies(
                    conn,
                    bucket=bucket,
                    stage_id=int(stage_id) if stage_id else None,
                    search=search,
                ),
                "page": page,
                "per_page": per_page,
            },
        ),
        postgres_loader=lambda _request_key: service.postgres.companies(
            bucket=bucket,
            stage_id=int(stage_id) if stage_id else None,
            search=search,
            order=order,
            page=page,
            per_page=per_page,
        ),
    )
    return json_response(request, result.payload, extra_headers=result.headers)


@router.get("/api/companies/{company_id}")
def get_company(request: Request, company_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_read(
            request,
            "companies.detail",
            extra={"company_id": company_id},
            legacy_loader=lambda: with_db(
                bridge,
                lambda conn: {"company": legacy_db.get_company(conn, company_id) or (_ for _ in ()).throw(KeyError("Company not found."))},
            ),
            postgres_loader=lambda _request_key: service.postgres.company(company_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/companies")
async def post_company(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "companies.create",
            extra={"ticker": payload.get("ticker", "")},
            operation=lambda: {
                "company": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.create_company(conn, payload)))
            },
            postgres_mutator=lambda: service.postgres.create_company(payload),
        )
        return json_response(request, result.payload, status_code=201, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.patch("/api/companies/{company_id}")
async def patch_company(request: Request, company_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "companies.update",
            extra={"company_id": company_id},
            operation=lambda: {
                "company": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.update_company(conn, company_id, payload)))
            },
            postgres_mutator=lambda: service.postgres.update_company(company_id, payload),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/templates")
def get_templates(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    result = service_from_request(request).execute_read(
        request,
        "templates.list",
        legacy_loader=lambda: with_db(bridge, lambda conn: {"templates": legacy_db.list_templates(conn)}),
        postgres_loader=lambda _request_key: service.postgres.templates(),
    )
    return json_response(request, result.payload, extra_headers=result.headers)


@router.get("/api/templates/{template_id}")
def get_template(request: Request, template_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_read(
            request,
            "templates.detail",
            extra={"template_id": template_id},
            legacy_loader=lambda: with_db(
                bridge,
                lambda conn: {"template": legacy_db.get_template(conn, template_id) or (_ for _ in ()).throw(KeyError("Template not found."))},
            ),
            postgres_loader=lambda _request_key: service.postgres.template(template_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/templates")
async def post_template(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "templates.create",
            operation=lambda: {
                "template": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.save_template(conn, payload)))
            },
            postgres_mutator=lambda: service.postgres.save_template(payload),
        )
        return json_response(request, result.payload, status_code=201, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.patch("/api/templates/{template_id}")
async def patch_template(request: Request, template_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    payload["id"] = template_id
    try:
        result = service_from_request(request).execute_write(
            request,
            "templates.update",
            extra={"template_id": template_id},
            operation=lambda: {
                "template": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.save_template(conn, payload)))
            },
            postgres_mutator=lambda: service.postgres.save_template(payload),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.delete("/api/templates/{template_id}")
def delete_template(request: Request, template_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "templates.delete",
            extra={"template_id": template_id},
            operation=lambda: with_db(bridge, lambda conn: (run_write(conn, lambda: legacy_db.delete_template(conn, template_id)), {"ok": True})[1]),
            postgres_mutator=lambda: service.postgres.delete_template(template_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/reports")
def get_reports(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    query = dict(request.query_params.multi_items())
    stage_id = query.get("stage_id")
    result = query.get("result")
    search = query.get("search")
    order = query.get("order")
    include_drafts_raw = query.get("include_drafts")
    include_drafts = legacy_db.parse_boolean_flag(include_drafts_raw, field_name="include_drafts") if include_drafts_raw is not None else False
    page = int(query.get("page") or "1")
    per_page = int(query.get("per_page") or "50")
    result_payload = service_from_request(request).execute_read(
        request,
        "reports.list",
        extra={
            "stage_id": stage_id,
            "result": result,
            "search": search,
            "order": order,
            "include_drafts": include_drafts,
            "page": page,
            "per_page": per_page,
        },
        legacy_loader=lambda: with_db(
            bridge,
            lambda conn: {
                "reports": legacy_db.list_report_summaries(
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
                "total": legacy_db.count_reports(
                    conn,
                    stage_id=int(stage_id) if stage_id else None,
                    result=result,
                    search=search,
                    include_drafts=include_drafts,
                ),
                "page": page,
                "per_page": per_page,
            },
        ),
        postgres_loader=lambda _request_key: service.postgres.reports(
            stage_id=int(stage_id) if stage_id else None,
            result=result,
            search=search,
            include_drafts=include_drafts,
            order=order,
            page=page,
            per_page=per_page,
        ),
    )
    return json_response(request, result_payload.payload, extra_headers=result_payload.headers)


@router.get("/api/reports/{report_id}")
def get_report(request: Request, report_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_read(
            request,
            "reports.detail",
            extra={"report_id": report_id},
            legacy_loader=lambda: with_db(
                bridge,
                lambda conn: {"report": legacy_db.get_report(conn, report_id) or (_ for _ in ()).throw(KeyError("Report not found."))},
            ),
            postgres_loader=lambda _request_key: service.postgres.report(report_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/reports/{report_id}/sections")
def get_report_sections(request: Request, report_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service.execute_read(
            request,
            "reports.sections.list",
            extra={"report_id": report_id},
            legacy_loader=lambda: with_db(bridge, lambda conn: legacy_db.list_report_sections(conn, report_id)),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/reports/{report_id}/sections/{section_id}")
def get_report_section(request: Request, report_id: int, section_id: str):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service.execute_read(
            request,
            "reports.sections.detail",
            extra={"report_id": report_id, "section_id": section_id},
            legacy_loader=lambda: with_db(bridge, lambda conn: legacy_db.get_report_section(conn, report_id, section_id)),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/reports/{report_id}/sections/{section_id}/preview")
async def post_report_section_preview(request: Request, report_id: int, section_id: str):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service.execute_write(
            request,
            "reports.sections.preview",
            extra={"report_id": report_id, "section_id": section_id},
            operation=lambda: with_db(bridge, lambda conn: legacy_db.preview_report_section(conn, report_id, section_id, payload)),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.patch("/api/reports/{report_id}/sections/{section_id}")
async def patch_report_section(request: Request, report_id: int, section_id: str):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service.execute_write(
            request,
            "reports.sections.update",
            extra={"report_id": report_id, "section_id": section_id},
            operation=lambda: with_db(
                bridge,
                lambda conn: run_write(conn, lambda: legacy_db.update_report_section(conn, report_id, section_id, payload)),
            ),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/reports")
async def post_report(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "reports.create",
            operation=lambda: {
                "report": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.create_report(conn, payload)))
            },
            postgres_mutator=lambda: service.postgres.create_report(payload),
        )
        return json_response(request, result.payload, status_code=201, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/reports/{report_id}/preview")
async def post_report_preview(request: Request, report_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "reports.preview",
            extra={"report_id": report_id},
            operation=lambda: with_db(bridge, lambda conn: legacy_db.preview_report_completion(conn, report_id, payload)),
            postgres_mutator=lambda: service.postgres.preview_report(report_id, payload),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.patch("/api/reports/{report_id}")
async def patch_report(request: Request, report_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "reports.update",
            extra={"report_id": report_id},
            operation=lambda: {
                "report": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.update_report(conn, report_id, payload)))
            },
            postgres_mutator=lambda: service.postgres.update_report(report_id, payload),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.delete("/api/reports/{report_id}")
def delete_report(request: Request, report_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "reports.delete",
            extra={"report_id": report_id},
            operation=lambda: {
                "company": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.delete_report(conn, report_id)))
            },
            postgres_mutator=lambda: service.postgres.delete_report(report_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/monitoring")
def get_monitoring(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    result = service_from_request(request).execute_read(
        request,
        "monitoring.list",
        legacy_loader=lambda: with_db(bridge, lambda conn: {"rules": legacy_db.list_monitoring_rules(conn, bucket="monitoring")}),
        postgres_loader=lambda _request_key: service.postgres.monitoring(),
    )
    return json_response(request, result.payload, extra_headers=result.headers)


@router.post("/api/monitoring-rules")
async def post_monitoring_rule(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "monitoring.create",
            operation=lambda: {
                "rule": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.save_monitoring_rule(conn, payload)))
            },
            postgres_mutator=lambda: service.postgres.save_monitoring_rule(payload),
        )
        return json_response(request, result.payload, status_code=201, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.patch("/api/monitoring-rules/{rule_id}")
async def patch_monitoring_rule(request: Request, rule_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    payload = await read_json_payload(request)
    payload["id"] = rule_id
    try:
        result = service_from_request(request).execute_write(
            request,
            "monitoring.update",
            extra={"rule_id": rule_id},
            operation=lambda: {
                "rule": with_db(bridge, lambda conn: run_write(conn, lambda: legacy_db.save_monitoring_rule(conn, payload)))
            },
            postgres_mutator=lambda: service.postgres.save_monitoring_rule(payload),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/documents")
async def post_document(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        payload = await read_upload_payload(request)
        files = payload.get("files") or []
        if not files:
            raise ValueError("At least one file is required.")
        result = service_from_request(request).execute_write(
            request,
            "documents.upload",
            extra={"company_id": payload.get("company_id"), "report_id": payload.get("report_id"), "file_count": len(files)},
            operation=lambda: with_db(
                bridge,
                lambda conn: {
                    "documents": [
                        run_write(
                            conn,
                            lambda item=item: legacy_db.save_document(
                                conn,
                                bridge.settings.upload_root,
                                int(payload["company_id"]),
                                item["filename"],
                                item["content"],
                                report_id=int(payload["report_id"]) if payload.get("report_id") else None,
                                notes=str(payload.get("notes") or ""),
                                mime_type=item.get("mime_type", ""),
                            ),
                        )
                        for item in files
                    ]
                },
            ),
            postgres_mutator=lambda: service.postgres.upload_documents(payload),
        )
        for document in result.payload.get("documents", []):
            storage_from_request(request).mirror_document_record(document)
        return json_response(request, result.payload, status_code=201, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/documents/{document_id}/status")
def get_document_status(request: Request, document_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_read(
            request,
            "documents.status",
            extra={"document_id": document_id},
            legacy_loader=lambda: with_db(
                bridge,
                lambda conn: {"document": legacy_db.document_status_record(conn, document_id) or (_ for _ in ()).throw(KeyError("Document not found."))},
            ),
            postgres_loader=lambda _request_key: service.postgres.document_status(document_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/documents/{document_id}/normalized")
def get_document_normalized(request: Request, document_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    storage = storage_from_request(request)
    try:
        result = service.execute_read(
            request,
            "documents.normalized",
            extra={"document_id": document_id},
            legacy_loader=lambda: with_db(
                bridge,
                lambda conn: {"document": legacy_db.get_document(conn, document_id) or (_ for _ in ()).throw(KeyError("Document not found."))},
            ),
            postgres_loader=lambda _request_key: service.postgres.document_record(document_id),
        )
        document = result.payload["document"]
        normalized_path = Path(document.get("normalized_text_path") or "")
        normalized_key = document.get("normalized_storage_key") or storage_key_from_path(
            bridge.settings.upload_root,
            document.get("normalized_text_path"),
            normalized_path.name,
        )
        if document.get("normalized_status") == legacy_db.DOCUMENT_STATUS_PENDING or not storage.object_exists(str(normalized_key), normalized_path):
            return api_error(request, "Normalized document is not ready yet.", 409, "document_pending")
        response, resolution = storage.response_for_file(
            key=str(normalized_key),
            local_path=normalized_path,
            media_type="text/plain; charset=utf-8",
            filename=f"{Path(document['original_name']).stem}-llm.txt",
            headers={**response_headers(request), **result.headers},
        )
        return apply_storage_resolution_headers(
            request,
            response,
            category="documents.normalized",
            result=result,
            resolution=resolution,
        )
    except Exception as exc:
        return handle_exception(request, exc)


@router.get("/api/documents/{document_id}/download")
def get_document_download(request: Request, document_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    storage = storage_from_request(request)
    try:
        result = service.execute_read(
            request,
            "documents.download",
            extra={"document_id": document_id},
            legacy_loader=lambda: with_db(
                bridge,
                lambda conn: {"document": legacy_db.get_document(conn, document_id) or (_ for _ in ()).throw(KeyError("Document not found."))},
            ),
            postgres_loader=lambda _request_key: service.postgres.document_record(document_id),
        )
        document = result.payload["document"]
        storage_path = Path(document["storage_path"])
        storage_key = document.get("storage_key") or storage_key_from_path(
            bridge.settings.upload_root,
            document.get("storage_path"),
            document.get("stored_name") or storage_path.name,
        )
        if not storage.object_exists(str(storage_key), storage_path):
            return api_error(request, "Document file is missing.", 404, "not_found")
        response, resolution = storage.response_for_file(
            key=str(storage_key),
            local_path=storage_path,
            media_type=document["mime_type"] or "application/octet-stream",
            filename=document["original_name"],
            headers={**response_headers(request), **result.headers},
        )
        return apply_storage_resolution_headers(
            request,
            response,
            category="documents.download",
            result=result,
            resolution=resolution,
        )
    except Exception as exc:
        return handle_exception(request, exc)


@router.post("/api/report-sources")
async def post_report_source(request: Request):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        payload = await read_upload_payload(request)
        files = payload.get("files") or []
        first_file = files[0] if files else None
        result = service_from_request(request).execute_write(
            request,
            "report_sources.create",
            extra={"report_id": payload.get("report_id")},
            operation=lambda: {
                "source": with_db(
                    bridge,
                    lambda conn: run_write(
                        conn,
                        lambda: legacy_db.save_report_source(
                            conn,
                            bridge.settings.upload_root,
                            int(payload["report_id"]) if payload.get("report_id") else None,
                            payload,
                            file_name=first_file["filename"] if first_file else None,
                            file_content=first_file["content"] if first_file else None,
                            file_mime_type=first_file.get("mime_type", "") if first_file else "",
                            file_origin=first_file.get("field", "") if first_file else "",
                        ),
                    ),
                )
            },
            postgres_mutator=lambda: service.postgres.save_report_source(
                payload,
                file_name=first_file["filename"] if first_file else None,
                file_content=first_file["content"] if first_file else None,
                file_mime_type=first_file.get("mime_type", "") if first_file else "",
                file_origin=first_file.get("field", "") if first_file else "",
            ),
        )
        source = result.payload.get("source") or {}
        if source.get("document_id"):
            with bridge.open_db() as conn:
                linked = legacy_db.get_document(conn, int(source["document_id"]))
            if linked:
                storage_from_request(request).mirror_document_record(linked)
        return json_response(request, result.payload, status_code=201, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.patch("/api/report-sources/{source_id}")
async def patch_report_source(request: Request, source_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        payload = await read_upload_payload(request)
        files = payload.get("files") or []
        first_file = files[0] if files else None
        payload["id"] = source_id
        result = service_from_request(request).execute_write(
            request,
            "report_sources.update",
            extra={"source_id": source_id, "report_id": payload.get("report_id")},
            operation=lambda: {
                "source": with_db(
                    bridge,
                    lambda conn: run_write(
                        conn,
                        lambda: legacy_db.save_report_source(
                            conn,
                            bridge.settings.upload_root,
                            int(payload["report_id"]) if payload.get("report_id") else None,
                            payload,
                            file_name=first_file["filename"] if first_file else None,
                            file_content=first_file["content"] if first_file else None,
                            file_mime_type=first_file.get("mime_type", "") if first_file else "",
                            file_origin=first_file.get("field", "") if first_file else "",
                        ),
                    ),
                )
            },
            postgres_mutator=lambda: service.postgres.save_report_source(
                payload,
                file_name=first_file["filename"] if first_file else None,
                file_content=first_file["content"] if first_file else None,
                file_mime_type=first_file.get("mime_type", "") if first_file else "",
                file_origin=first_file.get("field", "") if first_file else "",
            ),
        )
        source = result.payload.get("source") or {}
        if source.get("document_id"):
            with bridge.open_db() as conn:
                linked = legacy_db.get_document(conn, int(source["document_id"]))
            if linked:
                storage_from_request(request).mirror_document_record(linked)
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)


@router.delete("/api/report-sources/{source_id}")
def delete_report_source(request: Request, source_id: int):
    bridge = bridge_from_request(request)
    service = service_from_request(request)
    try:
        result = service_from_request(request).execute_write(
            request,
            "report_sources.delete",
            extra={"source_id": source_id},
            operation=lambda: with_db(bridge, lambda conn: (run_write(conn, lambda: legacy_db.delete_report_source(conn, source_id)), {"ok": True})[1]),
            postgres_mutator=lambda: service.postgres.delete_report_source(source_id),
        )
        return json_response(request, result.payload, extra_headers=result.headers)
    except Exception as exc:
        return handle_exception(request, exc)
