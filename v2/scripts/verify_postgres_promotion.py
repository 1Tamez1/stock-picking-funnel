from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
V1_ROOT = ROOT.parent

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.main import create_app
from funnel_app import db as legacy_db


@contextlib.contextmanager
def temporary_env(mapping: dict[str, str]):
    original = {key: os.environ.get(key) for key in mapping}
    try:
        os.environ.update(mapping)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    postgres_url = os.environ.get("FUNNEL_V2_POSTGRES_URL", "").strip()
    if not postgres_url or postgres_url.startswith("sqlite"):
        raise SystemExit("Set FUNNEL_V2_POSTGRES_URL to a real PostgreSQL connection string before running this script.")

    sqlite_path = Path(os.environ.get("FUNNEL_V2_SQLITE_PATH", V1_ROOT / "var" / "funnel.db")).expanduser().resolve()
    upload_dir = Path(os.environ.get("FUNNEL_V2_UPLOAD_DIR", V1_ROOT / "var" / "uploads")).expanduser().resolve()
    contract_dir = Path(os.environ.get("FUNNEL_V2_CONTRACT_DIR", ROOT / "contracts")).expanduser().resolve()

    env = {
        "FUNNEL_V2_BACKEND_MODE": "postgres_verify",
        "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
        "FUNNEL_V2_UPLOAD_DIR": str(upload_dir),
        "FUNNEL_V2_CONTRACT_DIR": str(contract_dir),
        "FUNNEL_V2_POSTGRES_URL": postgres_url,
    }

    with temporary_env(env):
        conn = legacy_db.connect(sqlite_path)
        try:
            company_id = int(conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()["id"])
            report_id = int(conn.execute("SELECT id FROM reports ORDER BY id LIMIT 1").fetchone()["id"])
            template_id = int(conn.execute("SELECT id FROM templates ORDER BY id LIMIT 1").fetchone()["id"])
        finally:
            conn.close()

        routes = [
            "/api/bootstrap",
            "/api/stages",
            "/api/companies",
            f"/api/companies/{company_id}",
            "/api/reports",
            f"/api/reports/{report_id}",
            "/api/templates",
            f"/api/templates/{template_id}",
            "/api/monitoring",
        ]

        results: list[dict[str, str | int]] = []
        with TestClient(create_app()) as client:
            auth_headers: dict[str, str] = {}
            api_token = os.environ.get("FUNNEL_V2_API_TOKEN", "").strip()
            owner_email = os.environ.get("FUNNEL_V2_OWNER_EMAIL", "").strip()
            owner_password = os.environ.get("FUNNEL_V2_OWNER_PASSWORD", "")
            if api_token:
                auth_headers["Authorization"] = f"Bearer {api_token}"
            elif owner_email and owner_password:
                login = client.post("/api/session/login", json={"email": owner_email, "password": owner_password})
                results.append(
                    {
                        "route": "/api/session/login",
                        "status_code": login.status_code,
                        "served_by": "",
                        "fallback": "",
                        "policy": "",
                    }
                )
            for route in routes:
                response = client.get(route, headers=auth_headers)
                results.append(
                    {
                        "route": route,
                        "status_code": response.status_code,
                        "served_by": response.headers.get("X-Funnel-Served-By", ""),
                        "fallback": response.headers.get("X-Funnel-Legacy-Fallback", ""),
                        "policy": response.headers.get("X-Funnel-Execution-Policy", ""),
                    }
                )

            report_preview = client.post(f"/api/reports/{report_id}/preview", json={"finalize": False}, headers=auth_headers)
            results.append(
                {
                    "route": f"/api/reports/{report_id}/preview",
                    "status_code": report_preview.status_code,
                    "served_by": report_preview.headers.get("X-Funnel-Served-By", ""),
                    "fallback": report_preview.headers.get("X-Funnel-Legacy-Fallback", ""),
                    "policy": report_preview.headers.get("X-Funnel-Execution-Policy", ""),
                }
            )

            live_report = client.get(f"/api/reports/{report_id}", headers=auth_headers)
            if live_report.status_code == 200:
                report_payload = (live_report.json() or {}).get("report") or {}
                readonly = set(report_payload.get("agent_contract", {}).get("readonly_field_ids") or [])
                readonly.update(report_payload.get("auto_inherited_fields") or [])

                def strip_readonly(mapping):
                    return {key: value for key, value in (mapping or {}).items() if key not in readonly}

                report_update = client.patch(
                    f"/api/reports/{report_id}",
                    json={
                        "expected_revision": int(report_payload.get("revision") or 0),
                        "finalize": False,
                        "title": report_payload.get("title") or "",
                        "report_month": report_payload.get("report_month") or "",
                        "result": report_payload.get("result") or "",
                        "summary": report_payload.get("summary") or "",
                        "watchlist_conditions": report_payload.get("watchlist_conditions") or "",
                        "watchlist_subjective_rules": report_payload.get("watchlist_subjective_rules") or "",
                        "archive_red_flags": report_payload.get("archive_red_flags") or "",
                        "next_action": report_payload.get("next_action") or "",
                        "review_date": report_payload.get("review_date") or "",
                        "responses": strip_readonly(report_payload.get("responses")),
                        "metrics": strip_readonly(report_payload.get("metrics")),
                        "section_ratings": dict(report_payload.get("section_ratings") or {}),
                        "data_quality": dict(report_payload.get("data_quality") or {}),
                        "field_sources": dict(report_payload.get("field_sources") or {}),
                        "field_notes": dict(report_payload.get("field_notes") or {}),
                        "field_exceptions": strip_readonly(report_payload.get("field_exceptions")),
                        "watchlist_objective_rules": list(report_payload.get("watchlist_objective_rules") or []),
                    },
                    headers=auth_headers,
                )
                results.append(
                    {
                        "route": f"/api/reports/{report_id}",
                        "status_code": report_update.status_code,
                        "served_by": report_update.headers.get("X-Funnel-Served-By", ""),
                        "fallback": report_update.headers.get("X-Funnel-Legacy-Fallback", ""),
                        "policy": report_update.headers.get("X-Funnel-Execution-Policy", ""),
                    }
                )

                report_source = client.post(
                    "/api/report-sources",
                    json={
                        "report_id": report_id,
                        "title": "Postgres Verify Source",
                        "source_type": "filing",
                        "evidence_grade": "A",
                        "confidence": "high",
                        "url": "https://example.com/postgres-verify-source",
                        "citation": "Postgres verify URL-only source.",
                        "notes": "Promotion verification source.",
                        "tags": "postgres,verify",
                        "link_only_reason": "Intentional verify-only URL source.",
                        "snapshot_guidance_acknowledged": True,
                    },
                    headers=auth_headers,
                )
                source_id = int(((report_source.json() or {}).get("source") or {}).get("id") or 0) if report_source.status_code == 201 else 0
                results.append(
                    {
                        "route": "/api/report-sources",
                        "status_code": report_source.status_code,
                        "served_by": report_source.headers.get("X-Funnel-Served-By", ""),
                        "fallback": report_source.headers.get("X-Funnel-Legacy-Fallback", ""),
                        "policy": report_source.headers.get("X-Funnel-Execution-Policy", ""),
                    }
                )
                if source_id:
                    source_update = client.patch(
                        f"/api/report-sources/{source_id}",
                        json={
                            "id": source_id,
                            "report_id": report_id,
                            "title": "Postgres Verify Source",
                            "source_type": "filing",
                            "evidence_grade": "A",
                            "confidence": "high",
                            "url": "https://example.com/postgres-verify-source",
                            "citation": "Postgres verify URL-only source.",
                            "notes": "Updated promotion verification source.",
                            "tags": "postgres,verify,updated",
                            "link_only_reason": "Intentional verify-only URL source.",
                            "snapshot_guidance_acknowledged": True,
                        },
                        headers=auth_headers,
                    )
                    results.append(
                        {
                            "route": f"/api/report-sources/{source_id}",
                            "status_code": source_update.status_code,
                            "served_by": source_update.headers.get("X-Funnel-Served-By", ""),
                            "fallback": source_update.headers.get("X-Funnel-Legacy-Fallback", ""),
                            "policy": source_update.headers.get("X-Funnel-Execution-Policy", ""),
                        }
                    )
                    source_delete = client.delete(f"/api/report-sources/{source_id}", headers=auth_headers)
                    results.append(
                        {
                            "route": f"/api/report-sources/{source_id}",
                            "status_code": source_delete.status_code,
                            "served_by": source_delete.headers.get("X-Funnel-Served-By", ""),
                            "fallback": source_delete.headers.get("X-Funnel-Legacy-Fallback", ""),
                            "policy": source_delete.headers.get("X-Funnel-Execution-Policy", ""),
                        }
                    )

            upload = client.post(
                "/api/documents",
                files={"file": ("verify-promotion.txt", b"verify promotion document", "text/plain")},
                data={"company_id": str(company_id), "notes": "verify promotion"},
                headers=auth_headers,
            )
            document_id = int(upload.json()["documents"][0]["id"]) if upload.status_code == 201 else 0
            results.append(
                {
                    "route": "/api/documents",
                    "status_code": upload.status_code,
                    "served_by": upload.headers.get("X-Funnel-Served-By", ""),
                    "fallback": upload.headers.get("X-Funnel-Legacy-Fallback", ""),
                    "policy": upload.headers.get("X-Funnel-Execution-Policy", ""),
                }
            )
            if document_id:
                for route in (
                    f"/api/documents/{document_id}/status",
                    f"/api/documents/{document_id}/download",
                ):
                    response = client.get(route, headers=auth_headers)
                    results.append(
                        {
                            "route": route,
                            "status_code": response.status_code,
                            "served_by": response.headers.get("X-Funnel-Served-By", ""),
                            "fallback": response.headers.get("X-Funnel-Legacy-Fallback", ""),
                            "policy": response.headers.get("X-Funnel-Execution-Policy", ""),
                        }
                    )

                conn = legacy_db.connect(sqlite_path)
                try:
                    row = conn.execute(
                        """
                        SELECT id
                        FROM documents
                        WHERE normalized_status NOT IN ('', 'pending')
                          AND normalized_text_path != ''
                        ORDER BY id
                        LIMIT 1
                        """
                    ).fetchone()
                    ready_document_id = int(row["id"]) if row else None
                finally:
                    conn.close()
                if ready_document_id is not None:
                    response = client.get(f"/api/documents/{ready_document_id}/normalized", headers=auth_headers)
                    results.append(
                        {
                            "route": f"/api/documents/{ready_document_id}/normalized",
                            "status_code": response.status_code,
                            "served_by": response.headers.get("X-Funnel-Served-By", ""),
                            "fallback": response.headers.get("X-Funnel-Legacy-Fallback", ""),
                            "policy": response.headers.get("X-Funnel-Execution-Policy", ""),
                        }
                    )

        print(json.dumps({"postgres_url": postgres_url, "results": results}, indent=2))


if __name__ == "__main__":
    main()
