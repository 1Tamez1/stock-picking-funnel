from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
API_ROOT = ROOT / "api"

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.integrity import audit_report_record
from app.integrity import audit_template_record
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


class IntegrityAuditTest(unittest.TestCase):
    def test_template_audit_detects_duplicate_ids_and_bad_options(self) -> None:
        template = {
            "id": 99,
            "stage_key": "screening",
            "schema": {
                "sections": [
                    {
                        "id": "section-a",
                        "title": "Section A",
                        "fields": [
                            {"id": "field-a", "label": "Result", "kind": "select", "options": ["Yes", "Yes", ""]},
                            {"id": "field-a", "label": "Duplicate", "kind": "text"},
                        ],
                    },
                    {
                        "id": "section-a",
                        "title": "Section B",
                        "fields": [],
                    },
                ]
            },
        }
        codes = {issue.code for issue in audit_template_record(template)}
        self.assertIn("duplicate_section_id", codes)
        self.assertIn("duplicate_field_id", codes)
        self.assertIn("duplicate_select_option", codes)
        self.assertIn("blank_select_option", codes)

    def test_report_audit_detects_orphaned_sources_and_unknown_fields(self) -> None:
        report = {
            "id": 11,
            "template": {
                "id": 5,
                "stage_key": "screening",
                "schema": {
                    "sections": [
                        {
                            "id": "section-a",
                            "title": "Section A",
                            "fields": [
                                {"id": "field-a", "label": "Decision", "kind": "text"},
                            ],
                        }
                    ]
                },
            },
            "responses": {"field-a": "ok", "missing-field": "bad"},
            "metrics": {},
            "section_ratings": {"missing-section": 3},
            "data_quality": {},
            "field_sources": {"field-a": {"source_ids": [99], "citation": "bad ref"}},
            "field_notes": {"missing-field": "bad note"},
            "field_exceptions": {"field-a": "not_real"},
            "sources": [{"id": 1}],
            "company_sources": [],
            "suggested_sources": [],
            "agent_contract": {"readonly_field_ids": ["missing-field"]},
            "auto_inherited_fields": [],
            "completion": {},
            "workflow": {},
            "watchlist_objective_rules": [],
        }
        codes = {issue.code for issue in audit_report_record(report)}
        self.assertIn("unknown_response_field", codes)
        self.assertIn("unknown_section_rating", codes)
        self.assertIn("orphaned_source_binding", codes)
        self.assertIn("unknown_note_key", codes)
        self.assertIn("invalid_exception_value", codes)
        self.assertIn("unknown_readonly_field", codes)

    def test_integrity_audit_script_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "contracts") as tempdir:
            runtime_root = Path(tempdir)
            sqlite_path = runtime_root / "funnel.db"
            upload_root = runtime_root / "uploads"
            shutil.copy2(V1_ROOT / "var" / "funnel.db", sqlite_path)
            shutil.copytree(V1_ROOT / "var" / "uploads", upload_root)
            env = {
                "FUNNEL_V2_BACKEND_MODE": "postgres_verify",
                "FUNNEL_V2_CONTRACT_DIR": str(runtime_root / "contracts"),
                "FUNNEL_V2_POSTGRES_URL": f"sqlite+pysqlite:///{(runtime_root / 'shadow.db').as_posix()}",
                "FUNNEL_V2_SQLITE_PATH": str(sqlite_path),
                "FUNNEL_V2_UPLOAD_DIR": str(upload_root),
            }
            manifest_path = runtime_root / "contracts" / "integrity" / "audit.json"
            with temporary_env(env):
                repair = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "repair_integrity.py"), "--apply"],
                    cwd=ROOT.parent,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(repair.returncode, 0, repair.stderr)
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "audit_integrity.py"), "--manifest-path", str(manifest_path)],
                    cwd=ROOT.parent,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("datasets", payload)
            self.assertGreaterEqual(len(payload["datasets"]), 1)
            self.assertEqual(payload["totals"]["critical_issue_count"], 0)
            self.assertGreater(payload["totals"]["source_issue_count"], 0)
            authoritative = next(item for item in payload["datasets"] if item["role"] == "authoritative_candidate")
            self.assertEqual(authoritative["critical_issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
