from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from funnel_app import db
from funnel_app.runtime import AppRuntime
from funnel_app.server import AppContext, FunnelHandler


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.context = AppContext(
            database=Path(self.tmp.name) / "funnel.db",
            uploads=Path(self.tmp.name) / "uploads",
        )
        self.runtime = AppRuntime(self.context)
        self.runtime.initialize(auto_confirm_seed=True)

    def tearDown(self) -> None:
        self.runtime.stop()
        self.tmp.cleanup()

    def dispatch(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        request_headers = headers or {}
        handler = FunnelHandler.__new__(FunnelHandler)
        handler.server = SimpleNamespace(runtime=self.runtime)
        handler.command = method
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.close_connection = True
        header_map = Message()
        for key, value in request_headers.items():
            header_map[key] = value
        if body is not None and "Content-Length" not in header_map:
            header_map["Content-Length"] = str(len(body))
        handler.headers = header_map
        handler.rfile = io.BytesIO(body or b"")
        handler.wfile = io.BytesIO()
        response_headers: dict[str, str] = {}
        handler.send_response = lambda status, message=None: setattr(handler, "_status", status)
        handler.send_header = lambda key, value: response_headers.__setitem__(key, value)
        handler.end_headers = lambda: None
        handler.log_request = lambda *args, **kwargs: None
        handler.log_message = lambda *args, **kwargs: None
        handler.prepare_request_context()

        parsed = urlparse(path)
        api_path = parsed.path.rstrip("/") or "/"
        if method == "GET":
            handler.handle_get_api(api_path, parse_qs(parsed.query))
        else:
            handler.handle_write_api(method, api_path)
        return int(getattr(handler, "_status", 200)), response_headers, handler.wfile.getvalue()

    def drain_jobs(self, max_jobs: int = 20) -> int:
        return db.drain_background_jobs(self.context.database, self.context.uploads, max_jobs=max_jobs)

    def request(self, method: str, path: str, payload: dict | None = None, headers: dict | None = None):
        body = None
        final_headers = headers or {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            final_headers = {"Content-Type": "application/json", **final_headers}
        status, _, raw = self.dispatch(method, path, body=body, headers=final_headers)
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if status >= 400:
            raise AssertionError(f"{method} {path} failed: {status} {parsed}")
        return parsed

    def request_with_status(
        self, method: str, path: str, payload: dict | None = None, headers: dict | None = None
    ) -> tuple[int, dict]:
        body = None
        final_headers = headers or {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            final_headers = {"Content-Type": "application/json", **final_headers}
        status, _, raw = self.dispatch(method, path, body=body, headers=final_headers)
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        return status, parsed

    def request_raw(self, method: str, path: str, payload: dict | None = None, headers: dict | None = None) -> bytes:
        body = None
        final_headers = headers or {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            final_headers = {"Content-Type": "application/json", **final_headers}
        status, _, raw = self.dispatch(method, path, body=body, headers=final_headers)
        if status >= 400:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            raise AssertionError(f"{method} {path} failed: {status} {parsed}")
        return raw

    def create_template(self, stage_id: int, *, name: str, markdown: str, description: str = "") -> dict:
        return self.request(
            "POST",
            "/api/templates",
            {
                "stage_id": stage_id,
                "name": name,
                "description": description,
                "markdown": markdown,
            },
        )["template"]

    def create_report(self, company_id: int, *, stage_id: int | None = None, template_id: int | None = None) -> dict:
        payload = {"company_id": company_id}
        if stage_id is not None:
            payload["stage_id"] = stage_id
        if template_id is not None:
            payload["template_id"] = template_id
        return self.request("POST", "/api/reports", payload)["report"]

    def field_ids(self, report: dict) -> dict[tuple[str, str], str]:
        return {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }

    def section_ids(self, report: dict) -> dict[str, str]:
        return {section["title"]: section["id"] for section in report["template"]["schema"]["sections"]}

    def create_ready_source(
        self,
        report_id: int,
        *,
        title: str = "Evidence packet",
        file_name: str = "evidence.txt",
        content: bytes = b"Evidence packet",
    ) -> dict:
        source = self.request(
            "POST",
            "/api/report-sources",
            {
                "report_id": report_id,
                "title": title,
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
                "file_name": file_name,
                "file_content_base64": base64.b64encode(content).decode("ascii"),
                "file_mime_type": "text/plain",
            },
        )["source"]
        self.drain_jobs()
        report = self.request("GET", f"/api/reports/{report_id}")["report"]
        return next(item for item in report["sources"] if int(item["id"]) == int(source["id"]))

    def patch_report(self, report_id: int, payload: dict, *, finalize: bool = False):
        report = self.request("GET", f"/api/reports/{report_id}")["report"]
        return self.request(
            "PATCH",
            f"/api/reports/{report_id}",
            {
                **payload,
                "expected_revision": report["revision"],
                "finalize": finalize,
            },
        )["report"]

    def required_field_notes(self, report: dict, field_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, str]:
        lookup = report["template"]["schema"]["field_lookup"]["by_id"]
        notes: dict[str, str] = {}
        for field_id in field_ids:
            field = lookup.get(field_id) or {}
            if not field.get("notes_required"):
                continue
            label = str(field.get("label") or field_id)
            category = str(field.get("note_category") or "")
            if category == "selection":
                notes[field_id] = f"Selected this option for {label} based on the cited evidence and the saved decision logic."
            elif category == "date":
                notes[field_id] = f"Date basis for {label}: taken from the cited evidence and interpreted exactly as saved here."
            else:
                notes[field_id] = f"Basis for {label}: taken from the cited evidence with the stated calculation or formatting choice."
        return notes

    def strict_override_rationale(self) -> str:
        return (
            "Override is temporary and explicit because the cited evidence already narrows the risk to a single bounded issue, "
            "the next step to verify it is named, and the decision would be reversed immediately if that verification fails."
        )

    def test_health_exposes_runtime_metadata_and_response_headers(self) -> None:
        status, headers, raw = self.dispatch("GET", "/api/health")
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("instance_id", payload)
        self.assertIn("started_at", payload)
        self.assertIn("pid", payload)
        self.assertIn("db_path", payload)
        self.assertIn("upload_dir", payload)
        self.assertIn("schema_version", payload)
        self.assertIn("worker", payload)
        self.assertEqual(headers["X-Funnel-Instance-Id"], payload["instance_id"])
        self.assertTrue(headers["X-Funnel-Request-Id"])

    def test_document_status_endpoint_tracks_pending_then_ready(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "DST", "name": "Document Status Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]
        document = self.request(
            "POST",
            "/api/documents",
            {
                "company_id": company["id"],
                "report_id": report["id"],
                "file_name": "packet.txt",
                "file_content_base64": base64.b64encode(b"Document status packet").decode("ascii"),
                "file_mime_type": "text/plain",
            },
        )["documents"][0]

        pending = self.request("GET", f"/api/documents/{document['id']}/status")["document"]
        self.assertEqual(document["normalized_status"], "pending")
        self.assertEqual(pending["normalized_status"], "pending")

        self.drain_jobs()
        ready = self.request("GET", f"/api/documents/{document['id']}/status")["document"]
        self.assertEqual(ready["normalized_status"], "ready")
        self.assertTrue(ready["normalized_available"])

    def test_url_only_source_requires_acknowledgment_and_reason(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "LNK", "name": "Link Validation Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]

        status, payload = self.request_with_status(
            "POST",
            "/api/report-sources",
            {
                "report_id": report["id"],
                "title": "Investor page",
                "source_type": "Investor presentation",
                "evidence_grade": "M",
                "confidence": "Medium",
                "url": "https://example.com/investor",
            },
        )
        self.assertEqual(status, 422)
        self.assertIn("snapshot_guidance_acknowledged", payload["error"])

        status, payload = self.request_with_status(
            "POST",
            "/api/report-sources",
            {
                "report_id": report["id"],
                "title": "Investor page",
                "source_type": "Investor presentation",
                "evidence_grade": "M",
                "confidence": "Medium",
                "url": "https://example.com/investor",
                "snapshot_guidance_acknowledged": True,
            },
        )
        self.assertEqual(status, 422)
        self.assertIn("link_only_reason", payload["error"])

    def test_finalize_blocks_cited_link_only_sources(self) -> None:
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Link-only Block Template",
            description="Compact template for link-only finalize coverage.",
            markdown="""
# Mini Link-only Block Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )
        company = self.request("POST", "/api/companies", {"ticker": "BLK", "name": "Blocked Link Corp"})["company"]
        report = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])
        fields = self.field_ids(report)
        source = self.request(
            "POST",
            "/api/report-sources",
            {
                "report_id": report["id"],
                "title": "Investor page",
                "source_type": "Investor presentation",
                "evidence_grade": "M",
                "confidence": "Medium",
                "url": "https://example.com/investor",
                "snapshot_guidance_acknowledged": True,
                "link_only_reason": "Snapshot upload still pending; keep the citation visible during the draft.",
            },
        )["source"]

        status, payload = self.request_with_status(
            "PATCH",
            f"/api/reports/{report['id']}",
            {
                "expected_revision": report["revision"],
                "finalize": True,
                "result": "Proceed to Next Step",
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "investor page",
                    }
                },
                "field_notes": self.required_field_notes(report, [fields[("Screening Handoff", "Final Decision")]]),
            },
        )

        self.assertEqual(status, 422)
        self.assertEqual(payload["code"], "report_completion_blocked")
        self.assertIn(fields[("Screening Handoff", "Final Decision")], payload["completion"]["blocked_source_field_ids"])

    def test_bootstrap_company_report_and_watchlist_flow(self) -> None:
        bootstrap = self.request("GET", "/api/bootstrap")
        self.assertNotIn("templates", bootstrap)
        self.assertEqual(len(bootstrap["stages"]), 7)
        self.assertEqual(bootstrap["stages"][0]["key"], "data_collection")
        self.assertEqual(bootstrap["stages"][1]["key"], "screening")
        data_collection = next(stage for stage in bootstrap["stages"] if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Data Collection Watchlist Template",
            description="Compact template for explicit finalization tests.",
            markdown="""
# Mini Data Collection Watchlist Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )

        company = self.request("POST", "/api/companies", {"ticker": "NKE", "name": "Nike"})["company"]
        report = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])
        fields = self.field_ids(report)
        source = self.create_ready_source(report["id"], title="Initial data packet", file_name="nke.txt", content=b"Nike packet")

        updated = self.patch_report(
            report["id"],
            {
                "result": "Watchlist",
                "summary": "Good business, wait for price.",
                "watchlist_conditions": "Re-screen below 35.",
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 35,
                        "current_value": 36,
                        "source": "Manual",
                    }
                ],
                "review_date": "2026-05-16",
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "initial packet",
                    }
                },
                "field_notes": self.required_field_notes(report, [fields[("Screening Handoff", "Final Decision")]]),
            },
            finalize=True,
        )
        self.assertEqual(updated["result"], "Watchlist")

        watchlist = self.request("GET", "/api/companies?bucket=watchlist")["companies"]
        rules = self.request("GET", "/api/monitoring")["rules"]
        self.assertEqual(watchlist[0]["ticker"], "NKE")
        self.assertEqual(watchlist[0]["watchlist_conditions"], "Re-screen below 35.")
        self.assertEqual(watchlist[0]["monitoring_rules"][0]["metric_name"], "Stock price")
        self.assertEqual(rules, [])

    def test_bootstrap_payload_omits_templates_and_stays_small(self) -> None:
        raw = self.request_raw("GET", "/api/bootstrap")
        payload = json.loads(raw.decode("utf-8"))
        self.assertNotIn("templates", payload)
        self.assertLessEqual(len(raw), 150 * 1024)

    def test_template_library_and_detail_endpoints_work_without_bootstrap_templates(self) -> None:
        bootstrap = self.request("GET", "/api/bootstrap")
        self.assertNotIn("templates", bootstrap)

        templates = self.request("GET", "/api/templates")["templates"]
        self.assertTrue(templates)
        self.assertNotIn("markdown", templates[0])

        detail = self.request("GET", f"/api/templates/{templates[0]['id']}")["template"]
        self.assertEqual(detail["id"], templates[0]["id"])
        self.assertIn("markdown", detail)

        screening_stage = next(stage for stage in bootstrap["stages"] if stage["key"] == "screening")
        created = self.request(
            "POST",
            "/api/templates",
            {
                "stage_id": screening_stage["id"],
                "name": "Screening API Test Template",
                "description": "Created via API test.",
                "markdown": "# Screening API Test Template\n\n## Decision\n\n- Verdict:\n",
            },
        )["template"]
        self.assertEqual(created["stage_id"], screening_stage["id"])

        templates = self.request("GET", "/api/templates")["templates"]
        self.assertIn(created["id"], [item["id"] for item in templates])

        status, payload = self.request_with_status("DELETE", f"/api/templates/{created['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        remaining = self.request("GET", "/api/templates")["templates"]
        self.assertNotIn(created["id"], [item["id"] for item in remaining])

    def test_report_create_rejects_mismatched_stage_and_template(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "MIS", "name": "Mismatch API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        screening = next(stage for stage in stages if stage["key"] == "screening")
        template = self.create_template(
            screening["id"],
            name="Screening-only Template",
            description="Used to assert mismatch rejection.",
            markdown="""
# Screening-only Template

## Decision
- Result: Pass / Watchlist / Archive
""",
        )

        status, payload = self.request_with_status(
            "POST",
            "/api/reports",
            {
                "company_id": company["id"],
                "stage_id": data_collection["id"],
                "template_id": template["id"],
            },
        )

        self.assertEqual(status, 422)
        self.assertIn("selected stage", payload["error"])

    def test_company_detail_returns_report_summaries_only_and_stays_small(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "SUM", "name": "Summary API Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]

        payload = self.request("GET", f"/api/companies/{company['id']}")["company"]
        self.assertEqual(len(payload["reports"]), 1)
        summary = payload["reports"][0]
        self.assertEqual(
            set(summary),
            {
                "id",
                "company_id",
                "title",
                "report_month",
                "result",
                "summary",
                "next_action",
                "review_date",
                "stage_id",
                "stage_key",
                "stage_name",
                "stage_sequence",
                "updated_at",
                "created_at",
            },
        )
        self.assertEqual(summary["id"], report["id"])
        for removed_key in (
            "responses",
            "metrics",
            "field_sources",
            "field_notes",
            "section_ratings",
            "data_quality",
            "watchlist_objective_rules",
            "template",
            "agent_contract",
        ):
            self.assertNotIn(removed_key, summary)

        raw = self.request_raw("GET", f"/api/companies/{company['id']}")
        self.assertLessEqual(len(raw), 200 * 1024)

    def test_reports_endpoint_defaults_to_completed_reports_sorted_by_completion_time(self) -> None:
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Reports Index Template",
            description="Compact template for reports index coverage.",
            markdown="""
# Mini Reports Index Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )

        company_a = self.request("POST", "/api/companies", {"ticker": "RPA", "name": "Report Alpha"})["company"]
        company_b = self.request("POST", "/api/companies", {"ticker": "RPB", "name": "Report Beta"})["company"]

        report_a = self.create_report(company_a["id"], stage_id=data_collection["id"], template_id=template["id"])
        fields_a = self.field_ids(report_a)
        source_a = self.create_ready_source(report_a["id"], title="Alpha packet", file_name="alpha.txt", content=b"alpha packet")
        self.patch_report(
            report_a["id"],
            {
                "result": "Archive",
                "summary": "Older completion summary.",
                "review_date": "2026-06-01",
                "field_sources": {
                    fields_a[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source_a["id"]],
                        "citation": "alpha packet",
                    }
                },
                "field_notes": self.required_field_notes(report_a, [fields_a[("Screening Handoff", "Final Decision")]]),
            },
            finalize=True,
        )

        draft = self.create_report(company_a["id"], stage_id=data_collection["id"], template_id=template["id"])

        report_b = self.create_report(company_b["id"], stage_id=data_collection["id"], template_id=template["id"])
        fields_b = self.field_ids(report_b)
        source_b = self.create_ready_source(report_b["id"], title="Beta packet", file_name="beta.txt", content=b"beta packet")
        self.patch_report(
            report_b["id"],
            {
                "result": "Archive",
                "summary": "Newer completion summary.",
                "review_date": "2026-06-15",
                "field_sources": {
                    fields_b[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source_b["id"]],
                        "citation": "beta packet",
                    }
                },
                "field_notes": self.required_field_notes(report_b, [fields_b[("Screening Handoff", "Final Decision")]]),
            },
            finalize=True,
        )

        conn = db.connect(self.context.database)
        try:
            conn.execute(
                "UPDATE reports SET completed_at = ?, updated_at = ? WHERE id = ?",
                ("2026-04-18T10:00:00+00:00", "2026-04-21T09:30:00+00:00", report_a["id"]),
            )
            conn.execute(
                "UPDATE reports SET completed_at = ?, updated_at = ? WHERE id = ?",
                ("2026-04-20T11:15:00+00:00", "2026-04-20T11:20:00+00:00", report_b["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        payload = self.request("GET", "/api/reports")
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["per_page"], 50)
        self.assertEqual([item["id"] for item in payload["reports"]], [report_b["id"], report_a["id"]])
        self.assertTrue(all(item["result"] != "Draft" for item in payload["reports"]))
        self.assertEqual(payload["reports"][0]["ticker"], "RPB")
        self.assertEqual(payload["reports"][0]["company_name"], "Report Beta")
        self.assertEqual(payload["reports"][0]["completed_at"], "2026-04-20T11:15:00+00:00")
        self.assertNotIn(draft["id"], [item["id"] for item in payload["reports"]])

    def test_reports_endpoint_can_include_drafts_and_completed_at_survives_non_finalize_edits(self) -> None:
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Reports Draft Toggle Template",
            description="Compact template for reports endpoint draft coverage.",
            markdown="""
# Mini Reports Draft Toggle Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )

        company = self.request("POST", "/api/companies", {"ticker": "RDR", "name": "Reports Draft Corp"})["company"]
        completed = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])
        fields = self.field_ids(completed)
        source = self.create_ready_source(completed["id"], title="Draft toggle packet", file_name="draft-toggle.txt", content=b"draft toggle packet")
        finalized = self.patch_report(
            completed["id"],
            {
                "result": "Archive",
                "summary": "Completed summary before edit.",
                "review_date": "2026-07-01",
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "draft toggle packet",
                    }
                },
                "field_notes": self.required_field_notes(completed, [fields[("Screening Handoff", "Final Decision")]]),
            },
            finalize=True,
        )
        completed_at = finalized["completed_at"]
        edited = self.patch_report(
            completed["id"],
            {
                "summary": "Edited after completion without re-finalizing.",
            },
        )
        self.assertEqual(edited["completed_at"], completed_at)

        draft = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])

        payload = self.request("GET", "/api/reports?include_drafts=true&result=Draft&search=RDR")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["reports"]), 1)
        self.assertEqual(payload["reports"][0]["id"], draft["id"])
        self.assertEqual(payload["reports"][0]["result"], "Draft")
        self.assertEqual(payload["reports"][0]["completed_at"], "")

    def test_multipart_document_upload_accepts_any_file_type(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "DOC", "name": "Document Corp"})["company"]
        boundary = "----funneltestboundary"
        file_body = b"binary\x00payload"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"company_id\"\r\n\r\n{company['id']}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"notes\"\r\n\r\ncustom file\r\n".encode(),
            (
                f"--{boundary}\r\n"
                "Content-Disposition: form-data; name=\"file\"; filename=\"evidence.anything\"\r\n"
                "Content-Type: application/x-anything\r\n\r\n"
            ).encode()
            + file_body
            + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)
        status, _, raw = self.dispatch(
            "POST",
            "/api/documents",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 201)
        self.assertEqual(payload["documents"][0]["original_name"], "evidence.anything")
        self.assertEqual(payload["documents"][0]["size_bytes"], len(file_body))
        self.assertIn("normalized_status", payload["documents"][0])

    def test_document_upload_rejects_cross_company_report_pairing(self) -> None:
        company_a = self.request("POST", "/api/companies", {"ticker": "DCA", "name": "Document Corp A"})["company"]
        company_b = self.request("POST", "/api/companies", {"ticker": "DCB", "name": "Document Corp B"})["company"]
        report_b = self.request("POST", "/api/reports", {"company_id": company_b["id"]})["report"]
        boundary = "----crosscompanyboundary"
        body = b"".join(
            [
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"company_id\"\r\n\r\n{company_a['id']}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"report_id\"\r\n\r\n{report_b['id']}\r\n".encode(),
                (
                    f"--{boundary}\r\n"
                    "Content-Disposition: form-data; name=\"file\"; filename=\"cross.txt\"\r\n"
                    "Content-Type: text/plain\r\n\r\n"
                ).encode()
                + b"cross-company payload\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )

        status, _, raw = self.dispatch(
            "POST",
            "/api/documents",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 422)
        self.assertIn("same company", payload["error"])
        company_payload = self.request("GET", f"/api/companies/{company_a['id']}")["company"]
        self.assertEqual(company_payload["documents"], [])

    def test_oversized_multipart_document_upload_returns_413_and_writes_nothing(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "BIG", "name": "Big Upload Corp"})["company"]
        self.runtime.context.max_upload_bytes = 128
        boundary = "----oversizedboundary"
        file_body = b"x" * 256
        body = b"".join(
            [
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"company_id\"\r\n\r\n{company['id']}\r\n".encode(),
                (
                    f"--{boundary}\r\n"
                    "Content-Disposition: form-data; name=\"file\"; filename=\"huge.txt\"\r\n"
                    "Content-Type: text/plain\r\n\r\n"
                ).encode()
                + file_body
                + b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )

        status, _, raw = self.dispatch(
            "POST",
            "/api/documents",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 413)
        self.assertIn("byte limit", payload["error"])
        company_payload = self.request("GET", f"/api/companies/{company['id']}")["company"]
        self.assertEqual(company_payload["documents"], [])

    def test_normalized_document_endpoint_and_company_sources(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "LLM", "name": "LLM Packet Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]
        boundary = "----llmboundary"
        fields = {
            "report_id": str(report["id"]),
            "title": "Quarterly snapshot",
            "source_type": "Quarterly report",
            "evidence_grade": "F",
            "confidence": "High",
        }
        body = b"".join(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            for key, value in fields.items()
        ) + (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename=\"snapshot.csv\"\r\n"
            "Content-Type: text/csv\r\n\r\n"
            "Metric,Value\r\nRevenue,15B\r\n".encode()
            + b"\r\n"
        ) + f"--{boundary}--\r\n".encode()

        status, _, raw = self.dispatch(
            "POST",
            "/api/report-sources",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 201)
        document_id = payload["source"]["document_id"]
        self.drain_jobs()

        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        self.assertEqual(len(report_payload["company_sources"]), 1)
        self.assertEqual(report_payload["company_sources"][0]["normalized_status"], "ready")

        raw = self.request_raw("GET", f"/api/documents/{document_id}/normalized").decode("utf-8")
        self.assertIn("Revenue", raw)

    def test_report_source_import_accepts_link_metadata(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "SRC", "name": "Source Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]
        boundary = "----sourcesboundary"
        fields = {
            "report_id": str(report["id"]),
            "title": "Investor day slides",
            "source_type": "Investor day",
            "evidence_grade": "M",
            "confidence": "Medium",
            "tags": "moat,management",
            "url": "https://example.com/slides",
            "snapshot_guidance_acknowledged": "true",
            "link_only_reason": "Snapshot upload is still pending while the draft source pack is being assembled.",
            "citation": "slide 18",
            "notes": "Useful for claims to verify.",
        }
        body = b"".join(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            for key, value in fields.items()
        ) + f"--{boundary}--\r\n".encode()
        status, _, raw = self.dispatch(
            "POST",
            "/api/report-sources",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 201)
        self.assertEqual(payload["source"]["source_type"], "Investor day")
        self.assertEqual(payload["source"]["tags"], ["moat", "management"])
        self.assertEqual(payload["source"]["capture_state"], "link_only")

        source_id = payload["source"]["id"]
        updated_fields = {**fields, "title": "Updated investor day", "evidence_grade": "F"}
        updated_body = b"".join(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            for key, value in updated_fields.items()
        ) + f"--{boundary}--\r\n".encode()
        status, _, raw = self.dispatch(
            "PATCH",
            f"/api/report-sources/{source_id}",
            body=updated_body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(updated_body))},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["source"]["title"], "Updated investor day")
        self.assertEqual(payload["source"]["evidence_grade"], "F")

        status, payload = self.request_with_status("DELETE", f"/api/report-sources/{source_id}")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_data_collection_report_supports_json_inline_file_source_upload(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "JON", "name": "JSON Source Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Data Collection Source Template",
            description="Compact template for API source upload coverage.",
            markdown="""
# Mini Data Collection Source Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )
        report = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])

        encoded = base64.b64encode(b"Metric,Value\nRevenue,10\n").decode("ascii")
        source = self.request(
            "POST",
            "/api/report-sources",
            {
                "report_id": report["id"],
                "title": "Market snapshot",
                "source_type": "Dataset",
                "evidence_grade": "F",
                "confidence": "High",
                "citation": "row 1",
                "file_name": "snapshot.csv",
                "file_content_base64": encoded,
                "file_mime_type": "text/csv",
            },
        )["source"]
        self.drain_jobs()
        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        source = next(item for item in report_payload["sources"] if int(item["id"]) == int(source["id"]))
        fields = self.field_ids(report_payload)
        report_payload = self.patch_report(
            report["id"],
            {
                "result": "Watchlist",
                "review_date": "2026-05-16",
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Packet completion",
                        "comparator": "=",
                        "threshold_value": 1,
                        "unit": "event",
                    }
                ],
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {"source_ids": [source["id"]], "citation": "row 1"}
                },
                "field_notes": self.required_field_notes(report_payload, [fields[("Screening Handoff", "Final Decision")]]),
            },
            finalize=True,
        )

        self.assertEqual(source["normalized_status"], "ready")
        self.assertTrue(source["document_normalized_url"].endswith("/normalized"))
        self.assertIn("agent_contract", report_payload)
        self.assertEqual(report_payload["agent_contract"]["report_kind"], "data_collection")
        self.assertEqual(report_payload["result"], "Watchlist")
        self.assertEqual(
            report_payload["agent_contract"]["completion"]["normalized_ready_source_count"],
            1,
        )

    def test_oversized_inline_snapshot_returns_413_and_writes_nothing(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "JLG", "name": "JSON Large Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]
        self.runtime.context.max_upload_bytes = 256
        encoded = base64.b64encode(b"x" * 256).decode("ascii")

        status, payload = self.request_with_status(
            "POST",
            "/api/report-sources",
            {
                "report_id": report["id"],
                "title": "Too large snapshot",
                "source_type": "Dataset",
                "evidence_grade": "F",
                "confidence": "High",
                "file_name": "snapshot.csv",
                "file_content_base64": encoded,
                "file_mime_type": "text/csv",
            },
        )

        self.assertEqual(status, 413)
        self.assertIn("byte limit", payload["error"])
        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        self.assertEqual(report_payload["sources"], [])
        self.assertEqual(report_payload["documents"], [])

    def test_source_delete_bumps_revision_and_stale_save_returns_409(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "REV", "name": "Revision API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Revision Conflict Template",
            description="Used to assert source-delete conflict handling.",
            markdown="""
# Mini Revision Conflict Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )
        report = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])
        source = self.create_ready_source(report["id"], title="Revision packet", file_name="revision.txt", content=b"Revision packet")

        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        fields = self.field_ids(report_payload)
        updated = self.patch_report(
            report["id"],
            {
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "revision packet",
                    }
                },
            },
        )

        status, _ = self.request_with_status("DELETE", f"/api/report-sources/{source['id']}")
        self.assertEqual(status, 200)

        status, payload = self.request_with_status(
            "PATCH",
            f"/api/reports/{report['id']}",
            {
                "expected_revision": updated["revision"],
                "title": "Stale title edit",
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "revision packet",
                    }
                },
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "report_revision_conflict")

    def test_screening_report_syncs_final_decision_and_summary_from_fields(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "SCR", "name": "Screening API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        screening = next(stage for stage in stages if stage["key"] == "screening")
        template = self.create_template(
            screening["id"],
            name="Mini Screening Sync Template",
            description="Compact template for explicit screening finalization.",
            markdown="""
# Mini Screening Sync Template

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
- Primary reason:
- Main risk:
- Main thing to verify:
- Review date, if Watchlist:

## If It Goes To Watchlist
- Valuation Uncertainty:

## One-Page Screening Conclusion
- Next action:
""",
        )
        report = self.create_report(company["id"], stage_id=screening["id"], template_id=template["id"])
        source = self.create_ready_source(report["id"], title="Screening packet", file_name="screening.txt", content=b"Screening packet")

        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        fields = self.field_ids(report_payload)
        sections = self.section_ids(report_payload)
        report_payload = self.patch_report(
            report["id"],
            {
                "responses": {
                    fields[("Final Decision", "Decision")]: "Watchlist",
                    fields[("Final Decision", "Primary reason")]: "Price is too rich today.",
                    fields[("Final Decision", "Main risk")]: "Peak margin risk.",
                    fields[("Final Decision", "Main thing to verify")]: "Retention durability.",
                    fields[("Final Decision", "Review date, if Watchlist")]: "2026-06-15",
                    fields[("If It Goes To Watchlist", "Valuation Uncertainty")]: "Need cleaner normalized owner earnings.",
                    fields[("One-Page Screening Conclusion", "Next action")]: "Revisit after next quarterly filing.",
                },
                "field_sources": {
                    f"section:{sections['Final Decision']}": {"source_ids": [source["id"]], "citation": "screening packet"},
                    f"section:{sections['If It Goes To Watchlist']}": {
                        "source_ids": [source["id"]],
                        "citation": "screening packet",
                    },
                    f"section:{sections['One-Page Screening Conclusion']}": {
                        "source_ids": [source["id"]],
                        "citation": "screening packet",
                    },
                },
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 35,
                        "unit": "USD",
                    }
                ],
                "field_notes": self.required_field_notes(
                    report_payload,
                    [
                        fields[("Final Decision", "Decision")],
                        fields[("Final Decision", "Review date, if Watchlist")],
                    ],
                ),
            },
            finalize=True,
        )

        self.assertEqual(report_payload["result"], "Watchlist")
        self.assertIn("Primary reason: Price is too rich today.", report_payload["summary"])
        self.assertIn("Valuation Uncertainty: Need cleaner normalized owner earnings.", report_payload["watchlist_conditions"])
        self.assertEqual(report_payload["review_date"], "2026-06-15")
        self.assertEqual(report_payload["agent_contract"]["report_kind"], "screening")

    def test_watchlist_finalize_requires_objective_monitoring_rule(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "WRQ", "name": "Watchlist Rule API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        screening = next(stage for stage in stages if stage["key"] == "screening")
        template = self.create_template(
            screening["id"],
            name="Mini Screening Watchlist Rule Template",
            description="Compact template to require objective watchlist rules.",
            markdown="""
# Mini Screening Watchlist Rule Template

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
- Primary reason:
- Main risk:
- Main thing to verify:
- Review date, if Watchlist:

## If It Goes To Watchlist
- Valuation Uncertainty:

## One-Page Screening Conclusion
- Next action:
""",
        )
        report = self.create_report(company["id"], stage_id=screening["id"], template_id=template["id"])
        source = self.create_ready_source(report["id"], title="Watchlist packet", file_name="watchlist.txt", content=b"Watchlist packet")

        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        fields = self.field_ids(report_payload)
        sections = self.section_ids(report_payload)

        status, payload = self.request_with_status(
            "PATCH",
            f"/api/reports/{report['id']}",
            {
                "expected_revision": report["revision"],
                "finalize": True,
                "responses": {
                    fields[("Final Decision", "Decision")]: "Watchlist",
                    fields[("Final Decision", "Primary reason")]: "The setup is interesting but still needs a concrete trigger.",
                    fields[("Final Decision", "Main risk")]: "Price may remain too high without a valuation reset.",
                    fields[("Final Decision", "Main thing to verify")]: "Normalized earnings quality.",
                    fields[("Final Decision", "Review date, if Watchlist")]: "2026-07-01",
                    fields[("If It Goes To Watchlist", "Valuation Uncertainty")]: "Need a cleaner owner-earnings bridge.",
                    fields[("One-Page Screening Conclusion", "Next action")]: "Stay on watch until the trigger is met.",
                },
                "field_sources": {
                    f"section:{sections['Final Decision']}": {"source_ids": [source["id"]], "citation": "watchlist packet"},
                    f"section:{sections['If It Goes To Watchlist']}": {
                        "source_ids": [source["id"]],
                        "citation": "watchlist packet",
                    },
                    f"section:{sections['One-Page Screening Conclusion']}": {
                        "source_ids": [source["id"]],
                        "citation": "watchlist packet",
                    },
                },
                "field_notes": self.required_field_notes(
                    report_payload,
                    [
                        fields[("Final Decision", "Decision")],
                        fields[("Final Decision", "Review date, if Watchlist")],
                    ],
                ),
            },
        )

        self.assertEqual(status, 422)
        self.assertEqual(payload["code"], "report_completion_blocked")
        self.assertIn(
            "objective monitoring rule",
            " ".join(payload["completion"]["decision_requirements"]).lower(),
        )

    def test_preview_endpoint_uses_unsaved_payload_and_does_not_persist(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "PRV", "name": "Preview API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Preview Template",
            description="Preview endpoint coverage.",
            markdown="""
# Mini Preview Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )
        report = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])
        source = self.create_ready_source(report["id"], title="Preview packet", file_name="preview.txt", content=b"Preview packet")
        fields = self.field_ids(report)

        status, payload = self.request_with_status(
            "POST",
            f"/api/reports/{report['id']}/preview",
            {
                "expected_revision": report["revision"],
                "result": "Watchlist",
                "review_date": "2026-06-01",
                "watchlist_objective_rules": [
                    {"rule_key": "starter", "metric_name": "Share price", "comparator": "<=", "threshold_value": 25}
                ],
                "field_sources": {
                    fields[("Screening Handoff", "Final Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "preview packet",
                    }
                },
                "field_notes": self.required_field_notes(report, [fields[("Screening Handoff", "Final Decision")]]),
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["completion"]["status"], "complete")
        live_report = self.request("GET", f"/api/reports/{report['id']}")["report"]
        self.assertEqual(live_report["result"], "Draft")
        self.assertEqual(live_report["field_sources"], {})
        self.assertEqual(live_report["watchlist_objective_rules"], [])

    def test_preview_endpoint_matches_finalize_blockers_without_persisting(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "BLK", "name": "Preview Blockers Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        data_collection = next(stage for stage in stages if stage["key"] == "data_collection")
        template = self.create_template(
            data_collection["id"],
            name="Mini Preview Blockers Template",
            description="Preview blocker parity coverage.",
            markdown="""
# Mini Preview Blockers Template

## Screening Handoff
- Final Decision: Watchlist / Archive / Proceed to Next Step
""",
        )
        report = self.create_report(company["id"], stage_id=data_collection["id"], template_id=template["id"])
        fields = self.field_ids(report)
        source = self.request(
            "POST",
            "/api/report-sources",
            {
                "report_id": report["id"],
                "title": "Investor page",
                "source_type": "Investor presentation",
                "evidence_grade": "M",
                "confidence": "Medium",
                "url": "https://example.com/investor",
                "snapshot_guidance_acknowledged": True,
                "link_only_reason": "Testing preview blockers.",
            },
        )["source"]

        preview_payload = {
            "expected_revision": report["revision"],
            "result": "Watchlist",
            "review_date": "2026-06-15",
            "watchlist_objective_rules": [
                {"rule_key": "starter", "metric_name": "Share price", "comparator": "<=", "threshold_value": 25}
            ],
            "field_sources": {
                fields[("Screening Handoff", "Final Decision")]: {
                    "source_ids": [source["id"]],
                    "citation": "preview blocker packet",
                }
            },
        }

        preview = self.request("POST", f"/api/reports/{report['id']}/preview", preview_payload)
        self.assertIn(fields[("Screening Handoff", "Final Decision")], preview["completion"]["blocked_source_field_ids"])
        self.assertIn(fields[("Screening Handoff", "Final Decision")], preview["completion"]["missing_required_note_ids"])

        status, payload = self.request_with_status(
            "PATCH",
            f"/api/reports/{report['id']}",
            {
                **preview_payload,
                "finalize": True,
            },
        )
        self.assertEqual(status, 422)
        self.assertEqual(payload["completion"]["blocked_source_field_ids"], preview["completion"]["blocked_source_field_ids"])
        self.assertEqual(payload["completion"]["missing_required_note_ids"], preview["completion"]["missing_required_note_ids"])

    def test_archive_finalize_requires_review_date(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "ARV", "name": "Archive Review Date API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        business = next(stage for stage in stages if stage["key"] == "business_underwriting")
        template = self.create_template(
            business["id"],
            name="Mini Business Archive Review Date Template",
            description="Compact template to require review dates for archive decisions.",
            markdown="""
# Mini Business Archive Review Date Template

## Final Decision
- Decision: Pass Business Underwriting / Watchlist / Archive
- Primary reason:
- Main risk:

## If It Is Archived
- Red flag:
""",
        )
        report = self.create_report(company["id"], stage_id=business["id"], template_id=template["id"])
        source = self.create_ready_source(report["id"], title="Archive packet", file_name="archive.txt", content=b"Archive packet")

        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        fields = self.field_ids(report_payload)
        sections = self.section_ids(report_payload)

        status, payload = self.request_with_status(
            "PATCH",
            f"/api/reports/{report['id']}",
            {
                "expected_revision": report["revision"],
                "finalize": True,
                "responses": {
                    fields[("Final Decision", "Decision")]: "Archive",
                    fields[("Final Decision", "Primary reason")]: "The accounting red flag breaks the case.",
                    fields[("Final Decision", "Main risk")]: "The issue may be structural rather than cyclical.",
                    fields[("If It Is Archived", "Red flag")]: "Cash conversion does not reconcile with the filings.",
                },
                "field_sources": {
                    f"section:{sections['Final Decision']}": {"source_ids": [source["id"]], "citation": "archive packet"},
                    f"section:{sections['If It Is Archived']}": {"source_ids": [source["id"]], "citation": "archive packet"},
                },
                "field_notes": self.required_field_notes(report_payload, [fields[("Final Decision", "Decision")]]),
            },
        )

        self.assertEqual(status, 422)
        self.assertEqual(payload["code"], "report_completion_blocked")
        self.assertIn("review date", " ".join(payload["completion"]["decision_requirements"]).lower())

    def test_business_underwriting_report_exposes_generic_agent_contract(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "GBU", "name": "Generic Business API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        screening = next(stage for stage in stages if stage["key"] == "screening")
        business = next(stage for stage in stages if stage["key"] == "business_underwriting")
        screening_template = self.create_template(
            screening["id"],
            name="Mini Screening Proceed Template",
            description="Compact screening template for upstream workflow tests.",
            markdown="""
# Mini Screening Proceed Template

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
""",
        )
        business_template = self.create_template(
            business["id"],
            name="Mini Business Proceed Template",
            description="Compact business template for generic contract coverage.",
            markdown="""
# Mini Business Proceed Template

## Final Decision
- Decision: Pass Business Underwriting / Watchlist / Archive / Return to Underwriting
- Primary reason:
""",
        )

        screening_report = self.create_report(company["id"], stage_id=screening["id"], template_id=screening_template["id"])
        screening_source = self.create_ready_source(
            screening_report["id"],
            title="Screening packet",
            file_name="screening.txt",
            content=b"Screening packet",
        )
        screening_fields = self.field_ids(screening_report)
        self.patch_report(
            screening_report["id"],
            {
                "responses": {
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                },
                "field_sources": {
                    screening_fields[("Final Decision", "Decision")]: {
                        "source_ids": [screening_source["id"]],
                        "citation": "screening packet",
                    }
                },
                "field_notes": self.required_field_notes(
                    screening_report,
                    [screening_fields[("Final Decision", "Decision")]],
                ),
            },
            finalize=True,
        )

        report = self.create_report(company["id"], stage_id=business["id"], template_id=business_template["id"])
        source = self.create_ready_source(report["id"], title="Business packet", file_name="business.txt", content=b"Business packet")

        report_payload = self.request("GET", f"/api/reports/{report['id']}")["report"]
        fields = self.field_ids(report_payload)
        report_payload = self.patch_report(
            report["id"],
            {
                "responses": {
                    fields[("Final Decision", "Primary reason")]: "Business quality clears the bar.",
                    fields[("Final Decision", "Decision")]: "Pass Business Underwriting",
                },
                "field_sources": {
                    fields[("Final Decision", "Decision")]: {
                        "source_ids": [source["id"]],
                        "citation": "business packet",
                    },
                    fields[("Final Decision", "Primary reason")]: {
                        "source_ids": [source["id"]],
                        "citation": "business packet",
                    },
                },
                "field_notes": self.required_field_notes(report_payload, [fields[("Final Decision", "Decision")]]),
            },
            finalize=True,
        )

        self.assertEqual(report_payload["result"], "Proceed to Next Step")
        self.assertIn("Decision: Pass Business Underwriting", report_payload["summary"])
        self.assertIn("Primary reason: Business quality clears the bar.", report_payload["summary"])
        self.assertEqual(report_payload["agent_contract"]["report_kind"], "business_underwriting")
        self.assertEqual(report_payload["agent_contract"]["workflow"]["previous_reports"][0]["stage_key"], "screening")
        self.assertTrue(any(resource["kind"] == "workflow_report" for resource in report_payload["agent_contract"]["resources"]))

    def test_financial_underwriting_report_exposes_canonical_handoffs_and_suggested_sources(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "FINA", "name": "Financial API Contract Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        screening = next(stage for stage in stages if stage["key"] == "screening")
        business = next(stage for stage in stages if stage["key"] == "business_underwriting")
        management = next(stage for stage in stages if stage["key"] == "management_underwriting")
        financial = next(stage for stage in stages if stage["key"] == "financial_underwriting")
        screening_template = self.create_template(
            screening["id"],
            name="Mini Screening Chain Template",
            description="Compact screening template for workflow chain tests.",
            markdown="""
# Mini Screening Chain Template

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
""",
        )
        business_template = self.create_template(
            business["id"],
            name="Mini Business Chain Template",
            description="Compact business template for workflow chain tests.",
            markdown="""
# Mini Business Chain Template

## Final Decision
- Decision: Pass Business Underwriting / Watchlist / Archive / Return to Underwriting
""",
        )
        management_template = self.create_template(
            management["id"],
            name="Mini Management Chain Template",
            description="Compact management template for workflow chain tests.",
            markdown="""
# Mini Management Chain Template

## Final Decision
- Decision: Pass Management Underwriting / Watchlist / Archive / Return to Underwriting
""",
        )

        screening_report = self.create_report(company["id"], stage_id=screening["id"], template_id=screening_template["id"])
        screening_source = self.create_ready_source(
            screening_report["id"],
            title="Screening packet",
            file_name="screening.txt",
            content=b"Screening packet",
        )
        screening_fields = self.field_ids(screening_report)
        self.patch_report(
            screening_report["id"],
            {
                "responses": {
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                },
                "field_sources": {
                    screening_fields[("Final Decision", "Decision")]: {
                        "source_ids": [screening_source["id"]],
                        "citation": "screening packet",
                    }
                },
                "field_notes": self.required_field_notes(
                    screening_report,
                    [screening_fields[("Final Decision", "Decision")]],
                ),
            },
            finalize=True,
        )

        business_report = self.create_report(company["id"], stage_id=business["id"], template_id=business_template["id"])
        business_source = self.create_ready_source(
            business_report["id"],
            title="Business packet",
            file_name="business.txt",
            content=b"Business packet",
        )
        business_fields = self.field_ids(business_report)
        self.patch_report(
            business_report["id"],
            {
                "responses": {
                    business_fields[("Final Decision", "Decision")]: "Pass Business Underwriting",
                },
                "field_sources": {
                    business_fields[("Final Decision", "Decision")]: {
                        "source_ids": [business_source["id"]],
                        "citation": "business packet",
                    }
                },
                "field_notes": self.required_field_notes(
                    business_report,
                    [business_fields[("Final Decision", "Decision")]],
                ),
            },
            finalize=True,
        )

        management_report = self.create_report(
            company["id"], stage_id=management["id"], template_id=management_template["id"]
        )
        management_fields = self.field_ids(management_report)
        source_payload = self.request(
            "POST",
            "/api/report-sources",
            {
                "report_id": management_report["id"],
                "title": "Management handoff packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
                "file_name": "management.txt",
                "file_content_base64": base64.b64encode(b"Management handoff packet").decode("ascii"),
                "file_mime_type": "text/plain",
            },
        )["source"]
        self.drain_jobs()
        management_report = self.request("GET", f"/api/reports/{management_report['id']}")["report"]
        source_payload = next(
            item for item in management_report["sources"] if int(item["id"]) == int(source_payload["id"])
        )
        self.patch_report(
            management_report["id"],
            {
                "responses": {
                    management_fields[("Final Decision", "Decision")]: "Pass Management Underwriting",
                },
                "field_sources": {
                    management_fields[("Final Decision", "Decision")]: {
                        "source_ids": [source_payload["id"]],
                        "citation": "management decision support",
                    }
                },
                "field_notes": self.required_field_notes(
                    management_report,
                    [management_fields[("Final Decision", "Decision")]],
                ),
            },
            finalize=True,
        )

        financial_report = self.create_report(company["id"], stage_id=financial["id"])
        report_payload = self.request("GET", f"/api/reports/{financial_report['id']}")["report"]
        workflow = report_payload["agent_contract"]["workflow"]

        self.assertEqual(workflow["latest_upstream_report"]["stage_key"], "management_underwriting")
        self.assertEqual(
            [item["stage_key"] for item in workflow["latest_previous_reports"]],
            ["screening", "business_underwriting", "management_underwriting"],
        )
        self.assertTrue(report_payload["agent_contract"]["suggested_sources"])
        self.assertEqual(
            report_payload["agent_contract"]["suggested_sources"][0]["suggestion_reason"],
            "cited_in_latest_upstream_report",
        )
        self.assertEqual(
            report_payload["agent_contract"]["suggested_sources"][0]["stage_key"],
            "management_underwriting",
        )
        source_resource = next(
            resource
            for resource in report_payload["agent_contract"]["resources"]
            if resource["kind"] == "report_source" and resource["annotations"]["source_id"] == source_payload["id"]
        )
        self.assertTrue(source_resource["annotations"]["suggested_for_reuse"])
        self.assertEqual(
            source_resource["annotations"]["suggestion_reason"],
            "cited_in_latest_upstream_report",
        )

    def test_business_underwriting_report_inherits_screening_handoff_fields(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "BIA", "name": "Business Inherit API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        screening = next(stage for stage in stages if stage["key"] == "screening")
        business = next(stage for stage in stages if stage["key"] == "business_underwriting")
        screening_template = self.create_template(
            screening["id"],
            name="Mini Screening Handoff Template",
            description="Compact screening template for inherited field tests.",
            markdown="""
# Mini Screening Handoff Template

## Basic Inputs
- Company:

## Moat Hypothesis
- What is the moat? Do not name a moat type without evidence.:

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
- Main thing to verify:
""",
        )
        business_template = self.create_template(
            business["id"],
            name="Mini Business Inheritance Template",
            description="Compact business template exposing inherited screening fields.",
            markdown="""
# Mini Business Inheritance Template

## Inherited From Screening
- Company:
- Main moat hypothesis inherited from screening:
- Main business uncertainty left open by screening:
""",
        )

        screening_report = self.create_report(company["id"], stage_id=screening["id"], template_id=screening_template["id"])
        screening_source = self.create_ready_source(
            screening_report["id"],
            title="Screening handoff packet",
            file_name="handoff.txt",
            content=b"Screening handoff packet",
        )
        screening_fields = self.field_ids(screening_report)
        screening_sections = self.section_ids(screening_report)
        self.patch_report(
            screening_report["id"],
            {
                "responses": {
                    screening_fields[("Basic Inputs", "Company")]: "Business Inherit API Corp",
                    screening_fields[("Moat Hypothesis", "What is the moat? Do not name a moat type without evidence.")]: "Switching costs and route density.",
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                    screening_fields[("Final Decision", "Main thing to verify")]: "Retention by cohort.",
                },
                "field_sources": {
                    f"section:{screening_sections['Basic Inputs']}": {
                        "source_ids": [screening_source["id"]],
                        "citation": "handoff packet",
                    },
                    f"section:{screening_sections['Moat Hypothesis']}": {
                        "source_ids": [screening_source["id"]],
                        "citation": "handoff packet",
                    },
                    f"section:{screening_sections['Final Decision']}": {
                        "source_ids": [screening_source["id"]],
                        "citation": "handoff packet",
                    },
                },
                "field_notes": self.required_field_notes(
                    screening_report,
                    [screening_fields[("Final Decision", "Decision")]],
                ),
            },
            finalize=True,
        )

        business_report = self.create_report(company["id"], stage_id=business["id"], template_id=business_template["id"])
        business_fields = self.field_ids(business_report)

        self.assertEqual(business_report["inherited_screening"]["report_id"], screening_report["id"])
        self.assertEqual(
            business_report["responses"][business_fields[("Inherited From Screening", "Company")]],
            "Business Inherit API Corp",
        )
        self.assertEqual(
            business_report["responses"][business_fields[("Inherited From Screening", "Main moat hypothesis inherited from screening")]],
            "Switching costs and route density.",
        )
        self.assertEqual(
            business_report["responses"][business_fields[("Inherited From Screening", "Main business uncertainty left open by screening")]],
            "Retention by cohort.",
        )
        self.assertIn(business_fields[("Inherited From Screening", "Company")], business_report["auto_inherited_fields"])

    def test_finalize_returns_422_with_completion_blockers(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "BLK", "name": "Blocked Finalize API Corp"})["company"]
        stages = self.request("GET", "/api/stages")["stages"]
        screening = next(stage for stage in stages if stage["key"] == "screening")
        template = self.create_template(
            screening["id"],
            name="Mini Screening Blocker Template",
            description="Compact screening template for blocked finalize responses.",
            markdown="""
# Mini Screening Blocker Template

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
- Primary reason:
""",
        )
        report = self.create_report(company["id"], stage_id=screening["id"], template_id=template["id"])
        source = self.create_ready_source(report["id"], title="Sparse packet", file_name="sparse.txt", content=b"Sparse packet")
        fields = self.field_ids(report)

        status, payload = self.request_with_status(
            "PATCH",
            f"/api/reports/{report['id']}",
            {
                "expected_revision": report["revision"],
                "finalize": True,
                "responses": {
                    fields[("Final Decision", "Decision")]: "Pass Screening",
                },
                "field_sources": {
                    fields[("Final Decision", "Decision")]: {"source_ids": [source["id"]], "citation": "sparse packet"}
                },
            },
        )

        self.assertEqual(status, 422)
        self.assertEqual(payload["code"], "report_completion_blocked")
        self.assertEqual(payload["completion"]["status"], "in_progress")
        self.assertIn(fields[("Final Decision", "Primary reason")], payload["completion"]["missing_field_ids"])

    def test_template_delete_hides_template_from_library(self) -> None:
        templates = self.request("GET", "/api/templates")["templates"]
        screening = templates[0]
        company = self.request("POST", "/api/companies", {"ticker": "TMP", "name": "Template Corp"})["company"]
        self.request("POST", "/api/reports", {"company_id": company["id"]})

        status, payload = self.request_with_status("DELETE", f"/api/templates/{screening['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        remaining = self.request("GET", "/api/templates")["templates"]
        self.assertNotIn(screening["id"], [item["id"] for item in remaining])

    def test_report_delete_reverts_company_state(self) -> None:
        company = self.request("POST", "/api/companies", {"ticker": "DEL", "name": "Delete Report Corp"})["company"]
        report = self.request("POST", "/api/reports", {"company_id": company["id"]})["report"]

        status, payload = self.request_with_status("DELETE", f"/api/reports/{report['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["company"]["bucket"], "pool")
        company_payload = self.request("GET", f"/api/companies/{company['id']}")["company"]
        self.assertEqual(company_payload["reports"], [])


if __name__ == "__main__":
    unittest.main()
