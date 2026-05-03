from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import httpx

PROMOTED_POLICY = "postgres_primary_with_legacy_fallback"


class HostedValidationFailure(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        super().__init__(str(report.get("reason") or "Hosted validation failed."))
        self.report = report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deeper hosted validation flow against a live V2 stack.")
    parser.add_argument("--base-url", default=os.environ.get("FUNNEL_V2_HOSTED_BASE_URL", "").strip())
    parser.add_argument("--host-header", default=os.environ.get("FUNNEL_V2_HOSTED_HOST_HEADER", "").strip())
    parser.add_argument("--email", default=os.environ.get("FUNNEL_V2_OWNER_EMAIL", "").strip())
    parser.add_argument("--password", default=os.environ.get("FUNNEL_V2_OWNER_PASSWORD", ""))
    parser.add_argument("--api-token", default=os.environ.get("FUNNEL_V2_API_TOKEN", "").strip())
    parser.add_argument("--poll-timeout-seconds", type=int, default=int(os.environ.get("FUNNEL_V2_HOSTED_POLL_TIMEOUT", "45")))
    parser.add_argument("--artifact-dir", default=os.environ.get("FUNNEL_V2_HOSTED_ARTIFACT_DIR", "").strip())
    parser.add_argument("--manifest-path", default=os.environ.get("FUNNEL_V2_HOSTED_VALIDATION_MANIFEST", "").strip())
    parser.add_argument("--failure-report-path", default=os.environ.get("FUNNEL_V2_HOSTED_FAILURE_REPORT", "").strip())
    parser.add_argument(
        "--require-postgres-primary",
        action="store_true",
        default=os.environ.get("FUNNEL_V2_REQUIRE_POSTGRES_PRIMARY", "0").strip().lower() in {"1", "true", "yes", "on"},
    )
    return parser.parse_args()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def artifact_path_exists(path_value: str) -> bool:
    candidate = str(path_value or "").strip()
    if not candidate:
        return False
    return Path(candidate).exists()


def write_json(path: str | Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def request_record(route: str, response: httpx.Response, *, note: str = "", flow: str = "") -> dict[str, Any]:
    artifact_path = response.headers.get("X-Funnel-Parity-Artifact", "").strip()
    return {
        "route": route,
        "flow": flow,
        "status_code": response.status_code,
        "served_by": response.headers.get("X-Funnel-Served-By", ""),
        "fallback": response.headers.get("X-Funnel-Legacy-Fallback", ""),
        "policy": response.headers.get("X-Funnel-Execution-Policy", ""),
        "artifact_path": artifact_path,
        "artifact_exists": artifact_path_exists(artifact_path),
        "storage_fallback": response.headers.get("X-Funnel-Storage-Fallback", ""),
        "storage_artifact_path": response.headers.get("X-Funnel-Storage-Artifact", "").strip(),
        "storage_artifact_exists": artifact_path_exists(response.headers.get("X-Funnel-Storage-Artifact", "").strip()),
        "note": note,
    }


def fail_validation(
    *,
    reason: str,
    route: str = "",
    flow: str = "",
    service: str = "api",
    fallback_action: str = "validation_failed",
    parity_artifact: str = "",
    status_code: int = 0,
    results: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    report = {
        "created_at": utc_timestamp(),
        "service": service,
        "route": route,
        "flow": flow,
        "reason": reason,
        "fallback_action": fallback_action,
        "parity_artifact": parity_artifact,
        "status_code": status_code,
        "results": results or [],
    }
    if extra:
        report.update(extra)
    raise HostedValidationFailure(report)


def ensure_status(response: httpx.Response, *, expected: int | tuple[int, ...], route: str) -> None:
    allowed = (expected,) if isinstance(expected, int) else expected
    if response.status_code not in allowed:
        fail_validation(
            reason="unexpected_status_code",
            route=route,
            status_code=response.status_code,
            extra={
                "expected": list(allowed),
                "body": safe_json_or_text(response),
            },
        )


def safe_json_or_text(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return response.json()
        except ValueError:
            return response.text
    return response.text


def auth_headers(*, api_token: str, host_header: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if host_header:
        headers["Host"] = host_header
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def login_or_token(client: httpx.Client, *, email: str, password: str, api_token: str, host_header: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    headers = auth_headers(api_token=api_token, host_header=host_header)
    if api_token:
        return headers, results
    if not email or not password:
        fail_validation(
            reason="missing_credentials",
            service="validation",
            fallback_action="validation_blocked",
            extra={"detail": "Provide --api-token or owner --email/--password for hosted validation."},
        )
    response = client.post("/api/session/login", json={"email": email, "password": password}, headers=headers)
    results.append(request_record("/api/session/login", response, flow="session_login"))
    ensure_status(response, expected=201, route="/api/session/login")
    return headers, results


def build_report_patch_payload(report: dict[str, Any], *, finalize: bool) -> dict[str, Any]:
    readonly = set(report.get("agent_contract", {}).get("readonly_field_ids") or [])
    readonly.update(report.get("auto_inherited_fields") or [])

    def strip_readonly(mapping: dict[str, Any] | None) -> dict[str, Any]:
        source = mapping or {}
        return {key: value for key, value in source.items() if key not in readonly}

    return {
        "expected_revision": int(report.get("revision") or 0),
        "finalize": finalize,
        "title": str(report.get("title") or ""),
        "report_month": str(report.get("report_month") or ""),
        "result": str(report.get("result") or ""),
        "summary": str(report.get("summary") or ""),
        "watchlist_conditions": str(report.get("watchlist_conditions") or ""),
        "watchlist_subjective_rules": str(report.get("watchlist_subjective_rules") or ""),
        "archive_red_flags": str(report.get("archive_red_flags") or ""),
        "next_action": str(report.get("next_action") or ""),
        "review_date": str(report.get("review_date") or ""),
        "responses": strip_readonly(report.get("responses")),
        "metrics": strip_readonly(report.get("metrics")),
        "section_ratings": dict(report.get("section_ratings") or {}),
        "data_quality": dict(report.get("data_quality") or {}),
        "field_sources": dict(report.get("field_sources") or {}),
        "field_notes": dict(report.get("field_notes") or {}),
        "field_exceptions": strip_readonly(report.get("field_exceptions")),
        "watchlist_objective_rules": list(report.get("watchlist_objective_rules") or []),
    }


def choose_finalize_candidate(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any] | None:
    reports = client.get("/api/reports?include_drafts=true&per_page=50", headers=headers)
    ensure_status(reports, expected=200, route="/api/reports?include_drafts=true&per_page=50")
    for summary in (reports.json() or {}).get("reports") or []:
        if not str(summary.get("result") or "").strip() or str(summary.get("result")).lower() == "draft":
            continue
        detail_route = f"/api/reports/{int(summary['id'])}"
        detail = client.get(detail_route, headers=headers)
        ensure_status(detail, expected=200, route=detail_route)
        report = (detail.json() or {}).get("report") or {}
        completion = report.get("completion") or {}
        if str(completion.get("status") or "") in {"ready_to_finalize", "complete"}:
            return report
    return None


def choose_report_creation_target(client: httpx.Client, headers: dict[str, str]) -> tuple[int, int]:
    companies = client.get("/api/companies?per_page=50", headers=headers)
    ensure_status(companies, expected=200, route="/api/companies?per_page=50")
    company_rows = (companies.json() or {}).get("companies") or []
    if not company_rows:
        fail_validation(
            reason="missing_company_seed_data",
            route="/api/companies?per_page=50",
            flow="report_create",
            service="validation",
            fallback_action="validation_blocked",
        )
    bootstrap = client.get("/api/bootstrap", headers=headers)
    ensure_status(bootstrap, expected=200, route="/api/bootstrap")
    stage_rows = (bootstrap.json() or {}).get("stages") or []
    if not stage_rows:
        fail_validation(
            reason="missing_stage_seed_data",
            route="/api/bootstrap",
            flow="report_create",
            service="validation",
            fallback_action="validation_blocked",
        )
    return int(company_rows[0]["id"]), int(stage_rows[0]["id"])


def poll_document_ready(client: httpx.Client, headers: dict[str, str], document_id: int, *, timeout_seconds: int) -> httpx.Response:
    route = f"/api/documents/{document_id}/status"
    deadline = time.time() + timeout_seconds
    last_response: httpx.Response | None = None
    while time.time() < deadline:
        response = client.get(route, headers=headers)
        ensure_status(response, expected=200, route=route)
        last_response = response
        payload = response.json() or {}
        document = payload.get("document") or {}
        status = str(document.get("normalized_status") or "")
        if status and status != "pending":
            return response
        time.sleep(1.0)
    if last_response is None:
        fail_validation(
            reason="document_status_unreachable",
            route=route,
            flow="document_poll",
        )
    fail_validation(
        reason="document_status_timeout",
        route=route,
        flow="document_poll",
        status_code=last_response.status_code,
        extra={
            "body": safe_json_or_text(last_response),
        },
    )


def enforce_promotion_evidence(results: list[dict[str, Any]], *, require_postgres_primary: bool) -> None:
    for record in results:
        policy = str(record.get("policy") or "")
        if policy != PROMOTED_POLICY:
            continue
        served_by = str(record.get("served_by") or "")
        fallback = str(record.get("fallback") or "")
        artifact_path = str(record.get("artifact_path") or "")
        artifact_exists = bool(record.get("artifact_exists"))

        if fallback == "1" and (not artifact_path or not artifact_exists):
            fail_validation(
                reason="silent_promoted_fallback",
                route=str(record.get("route") or ""),
                flow=str(record.get("flow") or ""),
                fallback_action="request_local_fallback_without_artifact",
                parity_artifact=artifact_path,
                status_code=int(record.get("status_code") or 0),
                results=results,
            )
        if served_by and not artifact_path:
            fail_validation(
                reason="promoted_route_missing_parity_artifact",
                route=str(record.get("route") or ""),
                flow=str(record.get("flow") or ""),
                fallback_action="artifact_missing",
                status_code=int(record.get("status_code") or 0),
                results=results,
            )
        if artifact_path and not artifact_exists:
            fail_validation(
                reason="promoted_route_artifact_path_missing",
                route=str(record.get("route") or ""),
                flow=str(record.get("flow") or ""),
                fallback_action="artifact_missing",
                parity_artifact=artifact_path,
                status_code=int(record.get("status_code") or 0),
                results=results,
            )
        if require_postgres_primary and served_by != "postgres":
            fail_validation(
                reason="promoted_route_not_served_by_postgres",
                route=str(record.get("route") or ""),
                flow=str(record.get("flow") or ""),
                fallback_action="green_path_failed",
                parity_artifact=artifact_path,
                status_code=int(record.get("status_code") or 0),
                results=results,
            )
        storage_fallback = str(record.get("storage_fallback") or "")
        storage_artifact_path = str(record.get("storage_artifact_path") or "")
        storage_artifact_exists = bool(record.get("storage_artifact_exists"))
        if storage_fallback == "1" and (not storage_artifact_path or not storage_artifact_exists):
            fail_validation(
                reason="silent_storage_fallback",
                route=str(record.get("route") or ""),
                flow=str(record.get("flow") or ""),
                fallback_action="storage_fallback_without_artifact",
                parity_artifact=storage_artifact_path,
                status_code=int(record.get("status_code") or 0),
                results=results,
            )
        if require_postgres_primary and storage_fallback == "1":
            fail_validation(
                reason="storage_route_not_served_from_remote_authority",
                route=str(record.get("route") or ""),
                flow=str(record.get("flow") or ""),
                fallback_action="storage_green_path_failed",
                parity_artifact=storage_artifact_path,
                status_code=int(record.get("status_code") or 0),
                results=results,
            )


def summary(results: list[dict[str, Any]], *, require_postgres_primary: bool) -> dict[str, Any]:
    promoted = [record for record in results if str(record.get("policy") or "") == PROMOTED_POLICY]
    return {
        "total_requests": len(results),
        "promoted_requests": len(promoted),
        "postgres_served_requests": sum(1 for record in promoted if str(record.get("served_by") or "") == "postgres"),
        "fallback_requests": sum(1 for record in results if str(record.get("fallback") or "") == "1"),
        "require_postgres_primary": require_postgres_primary,
    }


def main() -> None:
    args = parse_args()
    base_url = (args.base_url or "http://127.0.0.1").rstrip("/")
    created_report_id = 0
    results: list[dict[str, Any]] = []
    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
    manifest_path = Path(args.manifest_path).resolve() if args.manifest_path else (artifact_dir / "validation-manifest.json" if artifact_dir else None)
    failure_report_path = Path(args.failure_report_path).resolve() if args.failure_report_path else (artifact_dir / "failure-report.json" if artifact_dir else None)

    try:
        with httpx.Client(base_url=base_url, follow_redirects=False, timeout=45.0) as client:
            base_headers = {"Host": args.host_header} if args.host_header else {}
            headers: dict[str, str] = {}
            try:
                health = client.get("/api/health", headers=base_headers)
                results.append(request_record("/api/health", health, flow="liveness"))
                ensure_status(health, expected=200, route="/api/health")

                headers, auth_results = login_or_token(
                    client,
                    email=args.email,
                    password=args.password,
                    api_token=args.api_token,
                    host_header=args.host_header,
                )
                results.extend(auth_results)

                for route, flow in (
                    ("/api/health/runtime", "runtime_health"),
                    ("/api/bootstrap", "bootstrap"),
                    ("/api/companies?per_page=20", "companies_list"),
                    ("/api/reports?include_drafts=true&per_page=20", "reports_list"),
                    ("/api/templates", "templates_list"),
                    ("/api/monitoring", "monitoring_list"),
                ):
                    response = client.get(route, headers=headers)
                    results.append(request_record(route, response, flow=flow))
                    ensure_status(response, expected=200, route=route)

                company_id, stage_id = choose_report_creation_target(client, headers)
                timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                report_title = f"Hosted Validation {timestamp}"
                create_route = "/api/reports"
                created = client.post(
                    create_route,
                    headers=headers,
                    json={
                        "company_id": company_id,
                        "stage_id": stage_id,
                        "title": report_title,
                        "report_month": datetime.utcnow().strftime("%B %Y"),
                    },
                )
                results.append(request_record(create_route, created, note=report_title, flow="report_create"))
                ensure_status(created, expected=201, route=create_route)
                created_report = (created.json() or {}).get("report") or {}
                created_report_id = int(created_report["id"])

                created_detail_route = f"/api/reports/{created_report_id}"
                created_detail = client.get(created_detail_route, headers=headers)
                results.append(request_record(created_detail_route, created_detail, flow="report_detail"))
                ensure_status(created_detail, expected=200, route=created_detail_route)
                created_report = (created_detail.json() or {}).get("report") or {}

                preview_route = f"/api/reports/{created_report_id}/preview"
                preview = client.post(preview_route, headers=headers, json=build_report_patch_payload(created_report, finalize=False))
                results.append(request_record(preview_route, preview, flow="report_preview"))
                ensure_status(preview, expected=200, route=preview_route)

                save_route = f"/api/reports/{created_report_id}"
                save = client.patch(save_route, headers=headers, json=build_report_patch_payload(created_report, finalize=False))
                results.append(request_record(save_route, save, note="save_draft", flow="report_save"))
                ensure_status(save, expected=200, route=save_route)
                created_report = (save.json() or {}).get("report") or created_report

                blocked_finalize = client.patch(save_route, headers=headers, json=build_report_patch_payload(created_report, finalize=True))
                results.append(request_record(save_route, blocked_finalize, note="blocked_finalize", flow="report_finalize_blocked"))
                ensure_status(blocked_finalize, expected=(200, 422), route=save_route)

                source_create = client.post(
                    "/api/report-sources",
                    headers=headers,
                    json={
                        "report_id": created_report_id,
                        "title": f"Hosted Source {timestamp}",
                        "source_type": "filing",
                        "evidence_grade": "A",
                        "confidence": "high",
                        "url": f"https://example.com/hosted-validation/{timestamp}",
                        "citation": "Hosted validation URL-only source.",
                        "notes": "Hosted validation source create/update/delete flow.",
                        "tags": "hosted,validation",
                        "link_only_reason": "Intentional URL-only validation source.",
                        "snapshot_guidance_acknowledged": True,
                    },
                )
                results.append(request_record("/api/report-sources", source_create, flow="source_create"))
                ensure_status(source_create, expected=201, route="/api/report-sources")
                source_id = int(((source_create.json() or {}).get("source") or {})["id"])

                source_update_route = f"/api/report-sources/{source_id}"
                source_update = client.patch(
                    source_update_route,
                    headers=headers,
                    json={
                        "id": source_id,
                        "report_id": created_report_id,
                        "title": f"Hosted Source {timestamp}",
                        "source_type": "filing",
                        "evidence_grade": "A",
                        "confidence": "high",
                        "url": f"https://example.com/hosted-validation/{timestamp}",
                        "citation": "Hosted validation URL-only source.",
                        "notes": "Updated hosted validation source note.",
                        "tags": "hosted,validation,updated",
                        "link_only_reason": "Intentional URL-only validation source.",
                        "snapshot_guidance_acknowledged": True,
                    },
                )
                results.append(request_record(source_update_route, source_update, flow="source_update"))
                ensure_status(source_update, expected=200, route=source_update_route)

                source_delete = client.delete(source_update_route, headers=headers)
                results.append(request_record(source_update_route, source_delete, note="delete_source", flow="source_delete"))
                ensure_status(source_delete, expected=200, route=source_update_route)

                upload = client.post(
                    "/api/documents",
                    headers=headers,
                    files={"file": ("hosted-validation.txt", f"Hosted validation document {timestamp}".encode("utf-8"), "text/plain")},
                    data={"company_id": str(company_id), "report_id": str(created_report_id), "notes": "Hosted validation document upload."},
                )
                results.append(request_record("/api/documents", upload, flow="document_upload"))
                ensure_status(upload, expected=201, route="/api/documents")
                document_id = int(((upload.json() or {}).get("documents") or [{}])[0]["id"])

                status_response = poll_document_ready(client, headers, document_id, timeout_seconds=args.poll_timeout_seconds)
                results.append(request_record(f"/api/documents/{document_id}/status", status_response, flow="document_status"))
                status_payload = status_response.json() or {}
                normalized_status = str((status_payload.get("document") or {}).get("normalized_status") or "")

                download_route = f"/api/documents/{document_id}/download"
                download = client.get(download_route, headers=headers)
                results.append(request_record(download_route, download, flow="document_download"))
                ensure_status(download, expected=200, route=download_route)

                if normalized_status in {"ready", "limited"}:
                    normalized_route = f"/api/documents/{document_id}/normalized"
                    normalized = client.get(normalized_route, headers=headers)
                    results.append(request_record(normalized_route, normalized, flow="document_normalized"))
                    ensure_status(normalized, expected=200, route=normalized_route)

                finalize_candidate = choose_finalize_candidate(client, headers)
                if finalize_candidate is not None:
                    finalize_route = f"/api/reports/{int(finalize_candidate['id'])}"
                    finalize = client.patch(finalize_route, headers=headers, json=build_report_patch_payload(finalize_candidate, finalize=True))
                    results.append(request_record(finalize_route, finalize, note="finalize_existing_candidate", flow="report_finalize"))
                    ensure_status(finalize, expected=200, route=finalize_route)
                    reopened = client.get(finalize_route, headers=headers)
                    results.append(request_record(finalize_route, reopened, note="reopen_after_finalize", flow="report_reopen"))
                    ensure_status(reopened, expected=200, route=finalize_route)
            finally:
                if created_report_id:
                    delete_route = f"/api/reports/{created_report_id}"
                    deleted = client.delete(delete_route, headers=headers or base_headers)
                    results.append(request_record(delete_route, deleted, note="cleanup_delete_created_report", flow="cleanup_delete_report"))
                    created_report_id = 0

        enforce_promotion_evidence(results, require_postgres_primary=args.require_postgres_primary)
        manifest = {
            "created_at": utc_timestamp(),
            "base_url": base_url,
            "host_header": args.host_header,
            "auth_mode": "bearer" if args.api_token else "session",
            "summary": summary(results, require_postgres_primary=args.require_postgres_primary),
            "results": results,
        }
        write_json(manifest_path, manifest)
        print(json.dumps(manifest, indent=2))
    except HostedValidationFailure as exc:
        report = {
            "created_at": utc_timestamp(),
            "base_url": base_url,
            "host_header": args.host_header,
            "auth_mode": "bearer" if args.api_token else "session",
            **exc.report,
        }
        write_json(failure_report_path, report)
        raise SystemExit(json.dumps(report, indent=2))
    except Exception as exc:  # pragma: no cover - defensive path
        report = {
            "created_at": utc_timestamp(),
            "base_url": base_url,
            "host_header": args.host_header,
            "auth_mode": "bearer" if args.api_token else "session",
            "service": "validation",
            "route": "",
            "flow": "",
            "reason": "unexpected_exception",
            "fallback_action": "validation_aborted",
            "parity_artifact": "",
            "status_code": 0,
            "results": results,
            "detail": str(exc),
        }
        write_json(failure_report_path, report)
        raise SystemExit(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
