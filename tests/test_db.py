from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from funnel_app import db
from tools.import_template import import_template as import_markdown_template


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "funnel.db"
        self.uploads = Path(self.tmp.name) / "uploads"
        db.setup_database(self.db_path, auto_confirm_seed=True)
        self.conn = db.connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def stage_id(self, key: str) -> int:
        row = self.conn.execute("SELECT id FROM stages WHERE key = ?", (key,)).fetchone()
        self.assertIsNotNone(row)
        return int(row["id"])

    def update_report(self, report_id: int, payload: dict[str, object], *, expected_revision: int | None = None):
        revision = expected_revision
        if revision is None:
            report = db.get_report(self.conn, report_id)
            self.assertIsNotNone(report)
            revision = int(report["revision"])
        return db.update_report(
            self.conn,
            report_id,
            {
                **payload,
                "expected_revision": revision,
            },
        )

    def drain_jobs(self, max_jobs: int = 20) -> int:
        return db.drain_background_jobs(self.db_path, self.uploads, max_jobs=max_jobs)

    def save_report_source_ready(self, *args, **kwargs):
        source = db.save_report_source(*args, **kwargs)
        self.drain_jobs()
        refreshed = db.get_report_source(self.conn, int(source["id"]))
        self.assertIsNotNone(refreshed)
        return refreshed

    def save_document_ready(self, *args, **kwargs):
        document = db.save_document(*args, **kwargs)
        self.drain_jobs()
        refreshed = db.get_document(self.conn, int(document["id"]))
        self.assertIsNotNone(refreshed)
        return refreshed

    def required_field_notes(self, report: dict[str, object], field_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, str]:
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

    def count_queries(self, callback):
        statements: list[str] = []

        def tracer(sql: str) -> None:
            normalized = sql.lstrip().upper()
            if normalized.startswith(("BEGIN", "COMMIT", "ROLLBACK", "PRAGMA")):
                return
            statements.append(sql)

        self.conn.set_trace_callback(tracer)
        try:
            result = callback()
        finally:
            self.conn.set_trace_callback(None)
        return len(statements), result

    def build_report_chain(self, deepest_stage_key: str):
        company = db.create_company(self.conn, {"ticker": f"{deepest_stage_key[:3].upper()}Q", "name": f"{deepest_stage_key} Corp"})
        reports: dict[str, dict[str, object]] = {}

        data_collection = db.create_report(self.conn, {"company_id": company["id"], "stage_id": self.stage_id("data_collection")})
        reports["data_collection"] = data_collection
        if deepest_stage_key == "data_collection":
            return company, reports

        self.pass_report(data_collection)

        screening = db.create_report(self.conn, {"company_id": company["id"], "stage_id": self.stage_id("screening")})
        reports["screening"] = screening
        if deepest_stage_key == "screening":
            return company, reports

        self.pass_report(screening)

        business = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        reports["business_underwriting"] = business
        if deepest_stage_key == "business_underwriting":
            return company, reports

        self.pass_report(business)

        management = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("management_underwriting")},
        )
        reports["management_underwriting"] = management
        if deepest_stage_key == "management_underwriting":
            return company, reports

        self.pass_report(management)

        financial = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("financial_underwriting")},
        )
        reports["financial_underwriting"] = financial
        return company, reports

    def pass_report(self, report: dict[str, object]) -> dict[str, object]:
        stage_key = str(report["stage_key"])
        if stage_key == "data_collection":
            return self.update_report(int(report["id"]), {"result": db.RESULT_PROCEED})

        decision_values = {
            "screening": "Pass Screening",
            "business_underwriting": "Pass Business Underwriting",
            "management_underwriting": "Pass Management Underwriting",
        }
        decision_field = db.get_section_field(report["template"]["schema"], "Final Decision", "Decision")
        self.assertIsNotNone(decision_field)
        return self.update_report(
            int(report["id"]),
            {
                "result": db.RESULT_PROCEED,
                "responses": {decision_field["id"]: decision_values[stage_key]},
            },
        )

    def test_seed_creates_funnel_stages_and_templates(self) -> None:
        stages = db.list_stages(self.conn)
        templates = db.list_templates(self.conn)

        self.assertEqual(len(stages), 7)
        self.assertEqual(stages[0]["key"], "data_collection")
        self.assertEqual(stages[1]["key"], "screening")
        self.assertEqual(len(templates), 7)
        self.assertEqual(templates[0]["name"], "Data Collection Template")
        self.assertEqual(templates[1]["name"], "Stock Candidate Screening Questionnaire v5")
        self.assertGreater(templates[1]["schema"]["field_count"], 100)

    def test_init_db_migrates_existing_reports_table_before_creating_completed_index(self) -> None:
        legacy_path = Path(self.tmp.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(
                """
                CREATE TABLE stages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    sequence INTEGER NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    bucket TEXT NOT NULL DEFAULT 'pool',
                    current_stage_id INTEGER REFERENCES stages(id),
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE templates (
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

                CREATE TABLE reports (
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            db.init_db(conn)

            report_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(reports)").fetchall()
            }
            self.assertIn("completed_at", report_columns)

            report_indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(reports)").fetchall()
            }
            self.assertIn("idx_reports_completed", report_indexes)
        finally:
            conn.close()

    def test_seed_defaults_prompts_twice_before_structural_seed(self) -> None:
        db_file = Path(self.tmp.name) / "unseeded.db"
        conn = db.connect(db_file)
        prompts: list[str] = []
        messages: list[str] = []
        answers = iter(["I UNDERSTAND", "BACKUP THEN APPLY"])
        backup_root = Path(self.tmp.name) / "seed-confirm-backups"

        try:
            db.init_db(conn)
            result = db.seed_defaults(
                conn,
                input_fn=lambda prompt: prompts.append(prompt) or next(answers),
                output_fn=messages.append,
                backup_root=backup_root,
            )
        finally:
            conn.close()

        self.assertEqual(
            prompts,
            [
                "WARNING: Type 'I UNDERSTAND' to continue: ",
                "WARNING: Type 'BACKUP THEN APPLY' to continue: ",
            ],
        )
        self.assertEqual(result["action"], "seeded")
        self.assertTrue(Path(result["backup"]["database_backup_path"]).exists())
        self.assertTrue(Path(result["backup"]["structure_manifest_path"]).exists())
        self.assertTrue(any(message.startswith("WARNING:") for message in messages))

    def test_seed_defaults_creates_backup_before_reseeding_template(self) -> None:
        backup_root = Path(self.tmp.name) / "seed-backups"
        stage_id = self.stage_id("screening")
        active = self.conn.execute(
            "SELECT id FROM templates WHERE stage_id = ? AND is_active = 1",
            (stage_id,),
        ).fetchone()
        self.assertIsNotNone(active)
        self.conn.execute("UPDATE templates SET is_active = 0 WHERE id = ?", (int(active["id"]),))
        self.conn.commit()

        result = db.seed_defaults(self.conn, auto_confirm=True, backup_root=backup_root)

        self.assertEqual(result["action"], "seeded")
        self.assertEqual(result["template_insert_count"], 1)
        self.assertTrue(Path(result["backup"]["database_backup_path"]).exists())
        self.assertTrue(Path(result["backup"]["structure_manifest_path"]).exists())

    def test_import_template_creates_backup_before_structure_change(self) -> None:
        backup_root = Path(self.tmp.name) / "import-backups"
        source = Path(self.tmp.name) / "replacement-template.md"
        source.write_text(
            "# Replacement Template\n\n"
            "## Decision\n\n"
            "- Result: Pass / Watchlist / Archive\n"
            "- Summary:\n",
            encoding="utf-8",
        )

        result = import_markdown_template(
            self.conn,
            stage_key="screening",
            source=source,
            name="Replacement Screening Template",
            description="Imported during test.",
            activate=True,
            auto_confirm=True,
            backup_root=backup_root,
        )

        self.assertEqual(result["action"], "created")
        self.assertTrue(Path(result["backup"]["database_backup_path"]).exists())
        self.assertTrue(Path(result["backup"]["structure_manifest_path"]).exists())
        active = self.conn.execute(
            """
            SELECT templates.name
            FROM templates
            JOIN stages ON stages.id = templates.stage_id
            WHERE stages.key = 'screening' AND templates.is_active = 1
            ORDER BY templates.id DESC
            LIMIT 1
            """
        ).fetchone()
        self.assertIsNotNone(active)
        self.assertEqual(active["name"], "Replacement Screening Template")

    def test_delete_template_hides_active_and_preserves_referenced_history(self) -> None:
        templates = db.list_templates(self.conn)
        screening = templates[0]
        company = db.create_company(self.conn, {"ticker": "TMP", "name": "Template Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        self.assertEqual(report["template_id"], screening["id"])

        db.delete_template(self.conn, screening["id"])

        remaining = db.list_templates(self.conn)
        self.assertNotIn(screening["id"], [item["id"] for item in remaining])
        historical = db.get_template(self.conn, screening["id"])
        self.assertIsNotNone(historical)
        self.assertEqual(historical["is_active"], 0)

    def test_template_edit_creates_new_active_version_and_preserves_existing_report_snapshot(self) -> None:
        company = db.create_company(self.conn, {"ticker": "SNP", "name": "Snapshot Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        editable_field = next(
            field
            for field in report["template"]["schema"]["fields"]
            if field["id"] not in report["auto_inherited_fields"] and field["kind"] not in {"metric", "number"}
        )
        original_template = report["template"]
        original_field_count = original_template["schema"]["field_count"]
        saved = self.update_report(
            report["id"],
            {"responses": {editable_field["id"]: "Pinned historical answer."}},
        )

        replacement = db.save_template(
            self.conn,
            {
                "id": original_template["id"],
                "stage_id": original_template["stage_id"],
                "name": f"{original_template['name']} vNext",
                "description": "Safer active version",
                "markdown": "# Replacement Template\n\n## Decision\n\n- New question:\n",
            },
        )

        preserved = db.get_report(self.conn, report["id"])
        self.assertNotEqual(replacement["id"], original_template["id"])
        self.assertEqual(replacement["is_active"], 1)
        self.assertEqual(db.get_template(self.conn, original_template["id"])["is_active"], 0)
        self.assertEqual(preserved["template_id"], original_template["id"])
        self.assertEqual(preserved["template"]["id"], original_template["id"])
        self.assertEqual(preserved["template"]["schema"]["field_count"], original_field_count)
        self.assertEqual(preserved["responses"][editable_field["id"]], "Pinned historical answer.")
        self.assertEqual(saved["revision"], preserved["revision"])

        self.conn.close()
        db.setup_database(self.db_path, auto_confirm_seed=True)
        self.conn = db.connect(self.db_path)

        restarted = db.get_report(self.conn, report["id"])
        self.assertEqual(restarted["template"]["id"], original_template["id"])
        self.assertEqual(restarted["template"]["schema"]["field_count"], original_field_count)
        self.assertEqual(restarted["responses"][editable_field["id"]], "Pinned historical answer.")

    def test_save_template_rejects_stage_change_for_existing_template(self) -> None:
        template = db.get_template(self.conn, db.list_templates(self.conn)[0]["id"])
        self.assertIsNotNone(template)
        different_stage_id = next(stage["id"] for stage in db.list_stages(self.conn) if stage["id"] != template["stage_id"])

        with self.assertRaisesRegex(ValueError, "cannot change its stage"):
            db.save_template(
                self.conn,
                {
                    "id": template["id"],
                    "stage_id": different_stage_id,
                    "name": template["name"],
                    "description": template["description"],
                    "markdown": template["markdown"],
                },
            )

    def test_company_report_result_moves_through_funnel(self) -> None:
        company = db.create_company(self.conn, {"ticker": "NKE", "name": "Nike"})
        self.assertEqual(company["bucket"], "pool")

        report = db.create_report(self.conn, {"company_id": company["id"], "report_month": "April 2026"})
        company = db.get_company(self.conn, company["id"])
        self.assertEqual(company["bucket"], "funnel")
        self.assertEqual(company["current_stage_key"], "data_collection")

        report = db.update_report(
            self.conn,
            report["id"],
            {
                "result": db.RESULT_PROCEED,
                "summary": "Core source pack is ready.",
                "responses": {},
                "metrics": {},
            },
        )
        company = db.get_company(self.conn, company["id"])
        self.assertEqual(company["bucket"], "funnel")
        self.assertEqual(company["current_stage_key"], "screening")

        report = db.create_report(self.conn, {"company_id": company["id"], "report_month": "April 2026"})
        report = db.update_report(
            self.conn,
            report["id"],
            {
                "result": db.RESULT_PROCEED,
                "summary": "Passes the initial screen.",
                "responses": {},
                "metrics": {},
            },
        )
        company = db.get_company(self.conn, company["id"])
        self.assertEqual(company["current_stage_key"], "business_underwriting")
        self.assertEqual(report["result"], db.RESULT_PROCEED)

    def test_create_report_rejects_mismatched_stage_and_template(self) -> None:
        company = db.create_company(self.conn, {"ticker": "MMT", "name": "Mismatch Template Corp"})
        screening_template = db.active_template_for_stage(self.conn, self.stage_id("screening"))
        self.assertIsNotNone(screening_template)

        with self.assertRaisesRegex(ValueError, "selected stage"):
            db.create_report(
                self.conn,
                {
                    "company_id": company["id"],
                    "stage_id": self.stage_id("data_collection"),
                    "template_id": screening_template["id"],
                },
            )

    def test_create_report_uses_template_stage_when_only_template_is_supplied(self) -> None:
        company = db.create_company(self.conn, {"ticker": "TPL", "name": "Template Stage Corp"})
        screening_template = db.active_template_for_stage(self.conn, self.stage_id("screening"))
        self.assertIsNotNone(screening_template)

        report = db.create_report(
            self.conn,
            {
                "company_id": company["id"],
                "template_id": screening_template["id"],
            },
        )
        company = db.get_company(self.conn, company["id"])

        self.assertEqual(report["stage_id"], screening_template["stage_id"])
        self.assertEqual(report["stage_key"], "screening")
        self.assertEqual(company["current_stage_key"], "screening")

    def test_delete_last_draft_report_returns_company_to_pool(self) -> None:
        company = db.create_company(self.conn, {"ticker": "DEL", "name": "Delete Draft Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        company = db.delete_report(self.conn, report["id"])

        self.assertEqual(company["bucket"], "pool")
        self.assertIsNone(company["current_stage_id"])
        self.assertEqual(company["reports"], [])

    def test_delete_completed_report_reverts_company_state_and_rules(self) -> None:
        company = db.create_company(self.conn, {"ticker": "REV", "name": "Revert Corp"})
        data_collection = db.create_report(self.conn, {"company_id": company["id"]})
        db.update_report(
            self.conn,
            data_collection["id"],
            {"result": db.RESULT_PROCEED},
        )
        screening = db.create_report(self.conn, {"company_id": company["id"], "stage_id": self.stage_id("screening")})
        db.update_report(
            self.conn,
            screening["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_conditions": "Re-screen below 20.",
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 20,
                        "current_value": 24,
                    }
                ],
            },
        )

        company = db.get_company(self.conn, company["id"])
        self.assertEqual(company["bucket"], "watchlist")
        self.assertEqual(len(db.list_monitoring_rules(self.conn, company_id=company["id"])), 1)

        company = db.delete_report(self.conn, screening["id"])

        self.assertEqual(company["bucket"], "funnel")
        self.assertEqual(company["current_stage_key"], "screening")
        self.assertEqual(db.list_monitoring_rules(self.conn, company_id=company["id"]), [])

    def test_watchlist_result_adds_summary_and_monitoring_rule(self) -> None:
        company = db.create_company(self.conn, {"ticker": "ACME", "name": "Acme Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        db.update_report(
            self.conn,
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "summary": "Strong business, wrong price.",
                "watchlist_conditions": "Re-screen if price is below 35.",
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 35,
                        "current_value": 40,
                        "source": "Manual",
                    }
                ],
                "next_action": "Track price weekly.",
                "review_date": "2026-05-16",
            },
        )

        company = db.get_company(self.conn, company["id"])
        rules = db.list_monitoring_rules(self.conn, company_id=company["id"])
        self.assertEqual(company["bucket"], "watchlist")
        self.assertEqual(company["watchlist_conditions"], "Re-screen if price is below 35.")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["triggered"], 0)

        updated_rule = db.save_monitoring_rule(
            self.conn,
            {
                "id": rules[0]["id"],
                "metric_name": "Stock price",
                "comparator": "<=",
                "threshold_value": 35,
                "current_value": 34,
                "source": "Manual",
            },
        )
        self.assertEqual(updated_rule["triggered"], 1)

    def test_monitoring_rule_patch_preserves_existing_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "MRL", "name": "Monitoring Rule Ltd"})
        rule = db.save_monitoring_rule(
            self.conn,
            {
                "company_id": company["id"],
                "metric_name": "Stock price",
                "comparator": "<=",
                "threshold_value": 35,
                "current_value": 40,
                "source": "Manual",
                "notes": "Original note.",
            },
        )

        updated = db.save_monitoring_rule(
            self.conn,
            {
                "id": rule["id"],
                "current_value": 34,
            },
        )

        self.assertEqual(updated["metric_name"], "Stock price")
        self.assertEqual(updated["threshold_value"], 35)
        self.assertEqual(updated["source"], "Manual")
        self.assertEqual(updated["notes"], "Original note.")
        self.assertEqual(updated["triggered"], 1)

    def test_report_owned_monitoring_rule_rejects_structural_edits(self) -> None:
        company = db.create_company(self.conn, {"ticker": "RPT", "name": "Report Rule Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        self.update_report(
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 35,
                        "current_value": 40,
                    }
                ],
            },
        )
        rule = db.list_monitoring_rules(self.conn, company_id=company["id"])[0]

        with self.assertRaisesRegex(ValueError, "current_value and notes"):
            db.save_monitoring_rule(
                self.conn,
                {
                    "id": rule["id"],
                    "threshold_value": 30,
                },
            )

        updated = db.save_monitoring_rule(
            self.conn,
            {
                "id": rule["id"],
                "current_value": 34,
                "notes": "Checked at close.",
            },
        )
        self.assertEqual(updated["current_value"], 34)
        self.assertEqual(updated["notes"], "Checked at close.")

    def test_monitoring_rule_reconciliation_deletes_removed_rules_and_preserves_runtime_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "REC", "name": "Reconcile Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        self.update_report(
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 35,
                        "current_value": 40,
                    },
                    {
                        "metric_name": "Net debt / EBITDA",
                        "comparator": "<=",
                        "threshold_value": 2,
                    },
                ],
            },
        )
        rules = db.list_monitoring_rules(self.conn, company_id=company["id"])
        price_rule = next(rule for rule in rules if rule["metric_name"] == "Stock price")
        db.save_monitoring_rule(
            self.conn,
            {
                "id": price_rule["id"],
                "current_value": 34,
                "notes": "Runtime note.",
            },
        )

        self.update_report(
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Stock price",
                        "comparator": "<=",
                        "threshold_value": 35,
                    }
                ],
            },
        )
        reconciled = db.list_monitoring_rules(self.conn, company_id=company["id"])
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["metric_name"], "Stock price")
        self.assertEqual(reconciled[0]["current_value"], 34)
        self.assertEqual(reconciled[0]["notes"], "Runtime note.")

        refreshed_report = db.get_report(self.conn, report["id"])
        decision_field = db.decision_field(refreshed_report["template"]["schema"])
        self.update_report(
            report["id"],
            {
                "result": db.RESULT_PROCEED,
                "watchlist_objective_rules": [],
                "responses": (
                    {decision_field["id"]: db.RESULT_PROCEED}
                    if decision_field and refreshed_report["template"]["stage_key"] != "screening"
                    else (
                        {decision_field["id"]: db.screening_decision_from_result(db.RESULT_PROCEED)}
                        if decision_field
                        else {}
                    )
                ),
            },
        )
        self.assertEqual(db.list_monitoring_rules(self.conn, company_id=company["id"]), [])

    def test_duplicate_watchlist_objective_rule_metric_names_are_allowed_when_rule_keys_differ(self) -> None:
        company = db.create_company(self.conn, {"ticker": "DUP", "name": "Duplicate Metrics Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        updated = self.update_report(
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_objective_rules": [
                    {"rule_key": "starter", "metric_name": "Stock price", "comparator": "<=", "threshold_value": 35},
                    {"rule_key": "size-up", "metric_name": "Stock price", "comparator": "<=", "threshold_value": 30},
                ],
            },
        )

        self.assertEqual(len(updated["watchlist_objective_rules"]), 2)
        self.assertEqual(
            [rule["rule_key"] for rule in updated["watchlist_objective_rules"]],
            ["starter", "size-up"],
        )
        self.assertEqual(len(db.list_monitoring_rules(self.conn, company_id=company["id"])), 2)

    def test_monitoring_rule_reconciliation_uses_rule_key_not_metric_name(self) -> None:
        company = db.create_company(self.conn, {"ticker": "KEY", "name": "Rule Key Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        self.update_report(
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_objective_rules": [
                    {"rule_key": "starter", "metric_name": "Stock price", "comparator": "<=", "threshold_value": 35},
                    {"rule_key": "size-up", "metric_name": "Stock price", "comparator": "<=", "threshold_value": 30},
                ],
            },
        )
        rules = sorted(db.list_monitoring_rules(self.conn, company_id=company["id"]), key=lambda item: item["report_rule_key"])
        starter_rule = next(rule for rule in rules if rule["report_rule_key"] == "starter")
        db.save_monitoring_rule(
            self.conn,
            {
                "id": starter_rule["id"],
                "current_value": 34,
                "notes": "Starter line runtime note.",
            },
        )

        self.update_report(
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "watchlist_objective_rules": [
                    {"rule_key": "size-up", "metric_name": "Stock price", "comparator": "<=", "threshold_value": 28},
                    {"rule_key": "starter", "metric_name": "Stock price", "comparator": "<=", "threshold_value": 35},
                ],
            },
        )

        reconciled = sorted(db.list_monitoring_rules(self.conn, company_id=company["id"]), key=lambda item: item["report_rule_key"])
        self.assertEqual([rule["report_rule_key"] for rule in reconciled], ["size-up", "starter"])
        starter_rule = next(rule for rule in reconciled if rule["report_rule_key"] == "starter")
        size_up_rule = next(rule for rule in reconciled if rule["report_rule_key"] == "size-up")
        self.assertEqual(starter_rule["current_value"], 34)
        self.assertEqual(starter_rule["notes"], "Starter line runtime note.")
        self.assertEqual(size_up_rule["threshold_value"], 28)

    def test_archive_result_and_any_file_upload(self) -> None:
        company = db.create_company(self.conn, {"ticker": "RED", "name": "Red Flag Inc"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        db.update_report(
            self.conn,
            report["id"],
            {
                "result": db.RESULT_ARCHIVE,
                "archive_red_flags": "Accounting concern.",
                "review_date": "2027-01-01",
            },
        )
        document = self.save_document_ready(
            self.conn,
            self.uploads,
            company["id"],
            "filing.customtype",
            b"opaque bytes",
            report_id=report["id"],
            notes="Any extension should be accepted.",
            mime_type="application/x-custom",
        )
        company = db.get_company(self.conn, company["id"])

        self.assertEqual(company["bucket"], "archive")
        self.assertEqual(company["archive_red_flags"], "Accounting concern.")
        self.assertEqual(document["size_bytes"], len(b"opaque bytes"))
        self.assertTrue(Path(document["storage_path"]).exists())

    def test_save_document_rejects_missing_report(self) -> None:
        company = db.create_company(self.conn, {"ticker": "MIS", "name": "Missing Report Corp"})

        with self.assertRaisesRegex(KeyError, "Report not found"):
            db.save_document(
                self.conn,
                self.uploads,
                company["id"],
                "missing.txt",
                b"payload",
                report_id=999999,
            )

    def test_save_document_rejects_cross_company_report_link(self) -> None:
        company_a = db.create_company(self.conn, {"ticker": "DOA", "name": "Document A"})
        company_b = db.create_company(self.conn, {"ticker": "DOB", "name": "Document B"})
        report_b = db.create_report(self.conn, {"company_id": company_b["id"]})

        with self.assertRaisesRegex(ValueError, "same company"):
            db.save_document(
                self.conn,
                self.uploads,
                company_a["id"],
                "cross-company.txt",
                b"payload",
                report_id=report_b["id"],
            )

    def test_document_normalization_and_company_source_library(self) -> None:
        company = db.create_company(self.conn, {"ticker": "PKT", "name": "Packet Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("data_collection")},
        )

        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Operating snapshot",
                "source_type": "Dataset",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="snapshot.csv",
            file_content=b"Metric,Value\nRevenue,15B\nMargin,22%\n",
            file_mime_type="text/csv",
        )

        updated_report = db.get_report(self.conn, report["id"])
        company = db.get_company(self.conn, company["id"])

        self.assertEqual(updated_report["sources"][0]["normalized_status"], "ready")
        self.assertIn("Revenue", updated_report["sources"][0]["normalized_preview"])
        self.assertEqual(company["company_sources"][0]["id"], source["id"])
        document = db.get_document(self.conn, int(updated_report["sources"][0]["document_id"]))
        self.assertTrue(Path(document["normalized_text_path"]).exists())

    def test_data_collection_report_exposes_agent_contract_and_completion(self) -> None:
        company = db.create_company(self.conn, {"ticker": "LLM", "name": "LLM Ready Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("data_collection")},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "FY2025 annual report",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
                "citation": "p. 1",
            },
            file_name="annual.txt",
            file_content=b"Annual report contents",
            file_mime_type="text/plain",
        )
        template = report["template"]
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in template["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            report["id"],
            {
                "responses": {
                    fields[("Basic Inputs", "Company")]: "LLM Ready Corp",
                    fields[("Basic Inputs", "Ticker")]: "LLM",
                    fields[("Basic Inputs", "Date")]: "2026-04-17",
                    fields[("Basic Inputs", "Analyst")]: "Codex",
                    fields[("Basic Inputs", "Primary exchange")]: "NYSE",
                    fields[("Basic Inputs", "Reporting currency")]: "USD",
                    fields[("Collection Scope", "What is the business model in one sentence?")]: "Sells enterprise software.",
                    fields[("Collection Scope", "What sources are mandatory before Screening can start?")]: "Annual report, quarterly report, proxy, debt, price, peer source.",
                    fields[("Collection Scope", "What sources would materially improve confidence but are not mandatory yet?")]: "Customer checks.",
                    fields[("Collection Scope", "What source gaps are still open?")]: "Proxy still missing.",
                    fields[("Collection Scope", "Result")]: "Partial",
                    fields[("Required Source Coverage", "Latest annual report / 10-K / annual filing - Status")]: "Collected",
                    fields[("Required Source Coverage", "Latest annual report / 10-K / annual filing - Primary Source")]: source["title"],
                    fields[("Required Source Coverage", "Latest quarterly report / 10-Q / interim filing - Status")]: "Missing",
                    fields[("Required Source Coverage", "Proxy / compensation filing - Status")]: "Missing",
                    fields[("Required Source Coverage", "Earnings call transcript or management commentary - Status")]: "Missing",
                    fields[("Required Source Coverage", "Investor presentation / investor day - Status")]: "Missing",
                    fields[("Required Source Coverage", "At least one competitor or peer source - Status")]: "Missing",
                    fields[("Required Source Coverage", "Price / market data source - Status")]: "Missing",
                    fields[("Required Source Coverage", "Capital structure / debt source - Status")]: "Missing",
                    fields[("Required Source Coverage", "Secondary industry / news source - Status")]: "Missing",
                    fields[("Source Quality And Readiness", "Which source is the anchor source for the business description?")]: "FY2025 annual report",
                    fields[("Source Quality And Readiness", "Which source is the anchor source for the financial snapshot?")]: "FY2025 annual report",
                    fields[("Source Quality And Readiness", "Which source is the anchor source for management and incentives?")]: "Proxy filing when collected.",
                    fields[("Source Quality And Readiness", "Which source is the weakest link in the packet, and why?")]: "Management incentives remain thin.",
                    fields[("Source Quality And Readiness", "What still requires manual visual review because tables, charts, or scanned pages may not survive normalization cleanly?")]: "Capital allocation tables.",
                    fields[("Source Quality And Readiness", "Result")]: "Adequate",
                    fields[("LLM-Ready Packet", "What should Screening read first?")]: "Start with the annual report.",
                    fields[("LLM-Ready Packet", "What should Screening ignore for now?")]: "Press releases.",
                    fields[("LLM-Ready Packet", "What extraction warnings or formatting caveats matter most?")]: "Review dense tables manually.",
                    fields[("LLM-Ready Packet", "What are the top three questions Screening should answer with this packet?")]: "Durability, leverage, valuation.",
                    fields[("LLM-Ready Packet", "Result")]: "Needs Work",
                    fields[("Screening Handoff", "Next action")]: "Collect the proxy and latest quarterly report.",
                    fields[("Screening Handoff", "Main missing input")]: "Proxy filing.",
                    fields[("Screening Handoff", "Verify manually against original source")]: "Share count table.",
                    fields[("Screening Handoff", "Revisit if better sources appear")]: "Debt maturity schedule.",
                    fields[("Screening Handoff", "Summary")]: "Packet is not ready to advance.",
                    fields[("Screening Handoff", "Final Decision")]: "Watchlist",
                },
            },
        )

        updated = db.get_report(self.conn, report["id"])
        contract = updated["agent_contract"]

        self.assertEqual(updated["result"], db.RESULT_WATCHLIST)
        self.assertEqual(contract["report_kind"], "data_collection")
        self.assertIn("duplicate_labels", updated["template"]["schema"]["field_lookup"])
        self.assertEqual(
            contract["sections"]["screening_handoff"]["next_action_field_id"],
            fields[("Screening Handoff", "Next action")],
        )
        self.assertEqual(contract["completion"]["status"], "in_progress")
        self.assertNotIn(
            "Top-level report result does not match the Screening Handoff final decision.",
            contract["completion"]["warnings"],
        )
        self.assertIn("Latest quarterly report / 10-Q / interim filing", contract["completion"]["missing_coverage_rows"])
        self.assertEqual(contract["completion"]["source_count"], 1)
        self.assertEqual(contract["resources"][0]["normalized_url"], source["document_normalized_url"])

    def test_screening_report_exposes_agent_contract_and_syncs_decision_state(self) -> None:
        company = db.create_company(self.conn, {"ticker": "SCN", "name": "Screening Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "FY2025 screening packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="screening.txt",
            file_content=b"Screening packet contents",
            file_mime_type="text/plain",
        )
        template = report["template"]
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in template["schema"]["fields"]
        }
        business_category_result = next(
            field["id"] for field in template["schema"]["fields"] if field["label"] == "Business Category Result"
        )
        updated = db.update_report(
            self.conn,
            report["id"],
            {
                "responses": {
                    fields[("Part I. Fast Kill Screen", "Fast Kill Result")]: "Continue",
                    fields[("Moat Hypothesis", "Business Quality Result")]: "Strong",
                    fields[("3. Rough Value Range", "Valuation Read")]: "Potentially reasonable",
                    fields[("Part VII. What Must Be True / What To Verify", "Fragility Read")]: "Some Fragility",
                    fields[("4. Base Rates And Outside View", "Munger Check Result")]: "Clear",
                    business_category_result: "Good Predictable",
                    fields[("Final Decision", "Decision")]: "Watchlist",
                    fields[("Final Decision", "Primary reason")]: "Good business, price too rich.",
                    fields[("Final Decision", "Main risk")]: "Margins may be cyclically high.",
                    fields[("Final Decision", "Main thing to verify")]: "Retention durability.",
                    fields[("Final Decision", "Next funnel stage")]: "Business Underwriting",
                    fields[("Final Decision", "Review date, if Watchlist")]: "2026-06-01",
                    fields[("If It Goes To Watchlist", "Business Quality Verification")]: "Need stronger retention evidence.",
                    fields[("One-Page Screening Conclusion", "Next action")]: "Revisit after the next 10-Q and customer checks.",
                    fields[("2. Psychology And Bias Audit", "Most important bias risk")]: "Anchoring to a prior valuation peak.",
                    fields[("If It Is Archived", "What would need to change before revisiting?")]: "Not relevant for current decision.",
                },
                "field_sources": {
                    field_id: {"source_ids": [source["id"]], "citation": "screening packet"}
                    for field_id in (
                        fields[("Part I. Fast Kill Screen", "Fast Kill Result")],
                        fields[("Moat Hypothesis", "Business Quality Result")],
                        fields[("3. Rough Value Range", "Valuation Read")],
                        fields[("Part VII. What Must Be True / What To Verify", "Fragility Read")],
                        fields[("4. Base Rates And Outside View", "Munger Check Result")],
                        business_category_result,
                        fields[("Final Decision", "Decision")],
                        fields[("Final Decision", "Primary reason")],
                        fields[("Final Decision", "Main risk")],
                        fields[("Final Decision", "Main thing to verify")],
                        fields[("Final Decision", "Next funnel stage")],
                        fields[("One-Page Screening Conclusion", "Next action")],
                    )
                },
            },
        )

        contract = updated["agent_contract"]
        self.assertEqual(updated["result"], db.RESULT_WATCHLIST)
        self.assertIn("Primary reason: Good business, price too rich.", updated["summary"])
        self.assertIn("Business Quality Verification: Need stronger retention evidence.", updated["watchlist_conditions"])
        self.assertEqual(updated["review_date"], "2026-06-01")
        self.assertEqual(contract["report_kind"], "screening")
        self.assertEqual(contract["completion"]["status"], "in_progress")
        self.assertEqual(contract["completion"]["final_decision"], "Watchlist")
        self.assertEqual(contract["resources"][0]["normalized_url"], source["document_normalized_url"])
        self.assertTrue(
            any(field["label"] == "Business Underwriting handoff 1" for field in contract["sections"]["pass_handoff"])
        )

    def test_explicit_finalize_blocks_sparse_report_with_completion_details(self) -> None:
        company = db.create_company(self.conn, {"ticker": "BLK", "name": "Blocked Finalize Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Sparse screening packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="screening.txt",
            file_content=b"Sparse screening packet",
            file_mime_type="text/plain",
        )
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }

        with self.assertRaises(db.ReportCompletionBlocked) as ctx:
            self.update_report(
                report["id"],
                {
                    "finalize": True,
                    "responses": {
                        fields[("Final Decision", "Decision")]: "Watchlist",
                        fields[("Final Decision", "Primary reason")]: "Interesting, but still too incomplete.",
                    },
                    "field_sources": {
                        fields[("Final Decision", "Decision")]: {"source_ids": [source["id"]], "citation": "screening packet"}
                    },
                },
            )

        completion = ctx.exception.completion
        self.assertEqual(completion["status"], "in_progress")
        self.assertTrue(completion["missing_field_ids"])
        self.assertIn(fields[("Final Decision", "Main risk")], completion["missing_field_ids"])

    def test_finalize_accepts_complete_report_with_field_exception(self) -> None:
        stage_id = self.stage_id("business_underwriting")
        template = db.save_template(
            self.conn,
            {
                "stage_id": stage_id,
                "name": "Mini Business Finalization Template",
                "description": "Compact finalization test template.",
                "markdown": """
# Mini Business Finalization Template

## Facts
**Core fact**:
**Missing disclosure**:

## Final Decision
- Decision: Watchlist / Archive / Proceed to Next Step
- Primary reason:
- Main risk:

## If It Goes To Watchlist
- Watchlist trigger:
""",
            },
        )
        company = db.create_company(self.conn, {"ticker": "FIN", "name": "Finalize Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": stage_id, "template_id": template["id"]},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Mini underwriting packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="mini.txt",
            file_content=b"Mini underwriting packet",
            file_mime_type="text/plain",
        )
        section_ids = {section["title"]: section["id"] for section in report["template"]["schema"]["sections"]}
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }
        missing_disclosure_id = fields[("Facts", "Missing disclosure")]
        base_payload = {
            "finalize": True,
            "review_date": "2026-07-01",
            "responses": {
                fields[("Facts", "Core fact")]: "Recurring revenue base is visible in filings.",
                fields[("Final Decision", "Decision")]: "Watchlist",
                fields[("Final Decision", "Primary reason")]: "Need one missing disclosure before passing.",
                fields[("Final Decision", "Main risk")]: "Disclosure gap could hide cyclicality.",
                fields[("If It Goes To Watchlist", "Watchlist trigger")]: "Revisit once the disclosure appears.",
            },
            "field_sources": {
                f"section:{section_ids['Facts']}": {"source_ids": [source["id"]], "citation": "mini packet"},
                f"section:{section_ids['Final Decision']}": {"source_ids": [source["id"]], "citation": "mini packet"},
                f"section:{section_ids['If It Goes To Watchlist']}": {"source_ids": [source["id"]], "citation": "mini packet"},
            },
            "field_notes": {
                **self.required_field_notes(report, [fields[("Final Decision", "Decision")]]),
                missing_disclosure_id: "The company does not disclose this number directly, so the field is covered as not disclosed.",
            },
            "field_exceptions": {
                missing_disclosure_id: "not_disclosed",
            },
        }

        with self.assertRaises(db.ReportCompletionBlocked) as ctx:
            self.update_report(report["id"], base_payload)

        self.assertIn(
            "objective monitoring rule",
            " ".join(ctx.exception.completion["decision_requirements"]).lower(),
        )

        updated = self.update_report(
            report["id"],
            {
                **base_payload,
                "watchlist_objective_rules": [
                    {
                        "metric_name": "Watchlist trigger",
                        "comparator": "=",
                        "threshold_value": 1,
                        "unit": "event",
                    }
                ],
            },
        )

        self.assertEqual(updated["result"], db.RESULT_WATCHLIST)
        self.assertEqual(updated["completion"]["status"], "complete")
        self.assertEqual(updated["completion"]["warnings"], [])

    def test_watchlist_finalize_requires_review_date(self) -> None:
        stage_id = self.stage_id("business_underwriting")
        template = db.save_template(
            self.conn,
            {
                "stage_id": stage_id,
                "name": "Mini Business Review Date Template",
                "description": "Compact template to require review dates for watchlist finalization.",
                "markdown": """
# Mini Business Review Date Template

## Facts
**Core fact**:

## Final Decision
- Decision: Watchlist / Archive / Proceed to Next Step
- Primary reason:
- Main risk:

## If It Goes To Watchlist
- Watchlist trigger:
""",
            },
        )
        company = db.create_company(self.conn, {"ticker": "RVD", "name": "Review Date Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": stage_id, "template_id": template["id"]},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Review date packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="review-date.txt",
            file_content=b"Review date packet",
            file_mime_type="text/plain",
        )
        section_ids = {section["title"]: section["id"] for section in report["template"]["schema"]["sections"]}
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }

        with self.assertRaises(db.ReportCompletionBlocked) as ctx:
            self.update_report(
                report["id"],
                {
                    "finalize": True,
                    "responses": {
                        fields[("Facts", "Core fact")]: "Recurring revenue is visible in filings.",
                        fields[("Final Decision", "Decision")]: "Watchlist",
                        fields[("Final Decision", "Primary reason")]: "The setup is interesting but valuation is not ready.",
                        fields[("Final Decision", "Main risk")]: "The market may keep pricing in peak conditions.",
                        fields[("If It Goes To Watchlist", "Watchlist trigger")]: "Revisit after a material valuation reset.",
                    },
                    "watchlist_objective_rules": [
                        {
                            "metric_name": "Share price",
                            "comparator": "<=",
                            "threshold_value": 25,
                            "unit": "USD",
                        }
                    ],
                    "field_sources": {
                        f"section:{section_ids['Facts']}": {"source_ids": [source["id"]], "citation": "review date packet"},
                        f"section:{section_ids['Final Decision']}": {
                            "source_ids": [source["id"]],
                            "citation": "review date packet",
                        },
                        f"section:{section_ids['If It Goes To Watchlist']}": {
                            "source_ids": [source["id"]],
                            "citation": "review date packet",
                        },
                    },
                    "field_notes": self.required_field_notes(report, [fields[("Final Decision", "Decision")]]),
                },
            )

        self.assertIn("review date", " ".join(ctx.exception.completion["decision_requirements"]).lower())

    def test_schema_exposes_note_policy_for_structured_fields(self) -> None:
        screening_company = db.create_company(self.conn, {"ticker": "NTP", "name": "Note Policy Corp"})
        screening_report = db.create_report(
            self.conn,
            {"company_id": screening_company["id"], "stage_id": self.stage_id("screening")},
        )
        screening_lookup = screening_report["template"]["schema"]["field_lookup"]["by_id"]
        screening_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in screening_report["template"]["schema"]["fields"]
        }

        decision_field = screening_lookup[screening_fields[("Final Decision", "Decision")]]
        primary_reason_field = screening_lookup[screening_fields[("Final Decision", "Primary reason")]]
        review_date_field = screening_lookup[screening_fields[("Final Decision", "Review date, if Watchlist")]]

        self.assertTrue(decision_field["notes_required"])
        self.assertFalse(primary_reason_field["notes_required"])
        self.assertTrue(review_date_field["notes_required"])
        self.assertTrue(decision_field["note_placeholder"])

        execution_company = db.create_company(self.conn, {"ticker": "NTE", "name": "Execution Notes Corp"})
        execution_report = db.create_report(
            self.conn,
            {"company_id": execution_company["id"], "stage_id": self.stage_id("execution_rules")},
        )
        execution_lookup = execution_report["template"]["schema"]["field_lookup"]["by_id"]
        execution_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in execution_report["template"]["schema"]["fields"]
        }
        worth_field = execution_lookup[execution_fields[("Final Decision", "Conservative worth per share")]]

        self.assertEqual(worth_field["kind"], "text")
        self.assertTrue(worth_field["notes_required"])
        self.assertEqual(worth_field["note_category"], "structured_text")

    def test_manual_text_note_policy_covers_representative_structured_fields_by_stage(self) -> None:
        stage_expectations = [
            ("screening", ("If It Passes Screening", "Valuation and Position Size issue"), True),
            ("business_underwriting", ("Final Decision", "Main question for Valuation and Position Size"), True),
            ("management_underwriting", ("If It Passes Management Underwriting", "Valuation and Position Size issue"), True),
            ("financial_underwriting", ("If It Passes Financial Underwriting", "Valuation and Position Size issue"), True),
            ("valuation_position_size", ("3. Buy, Add, And No-Buy Boundaries", "No-buy above"), True),
            ("valuation_position_size", ("4. Conservative Worth And Price Ladder", "What single assumption would move these lines the most?"), False),
            ("execution_rules", ("1. Master Snapshot Table", "Quote date and time - Value"), True),
            ("execution_rules", ("One-Page Execution Conclusion", "What the business is"), False),
        ]

        for index, (stage_key, field_ref, expected) in enumerate(stage_expectations, start=1):
            with self.subTest(stage_key=stage_key, field=field_ref):
                company = db.create_company(
                    self.conn,
                    {"ticker": f"{stage_key[:3].upper()}{index}", "name": f"{stage_key} note test {index}"},
                )
                report = db.create_report(self.conn, {"company_id": company["id"], "stage_id": self.stage_id(stage_key)})
                lookup = {
                    (field["section_title"], field["label"]): field
                    for field in report["template"]["schema"]["fields"]
                }
                self.assertEqual(bool(lookup[field_ref]["notes_required"]), expected)

    def test_screening_pass_requires_override_when_hard_gate_or_munger_do_not_clear(self) -> None:
        stage_id = self.stage_id("screening")
        template = db.save_template(
            self.conn,
            {
                "stage_id": stage_id,
                "name": "Mini Screening Override Template",
                "description": "Strict screening override checks.",
                "markdown": """
# Mini Screening Override Template

## Hard Gate Summary
| Hard Gate | Result | Main Note |
| --- | --- | --- |
| Operating history | Pass / Watchlist / Archive |  |
| Munger checks | Clear / Needs Verification / Archive |  |

## Final Decision
- Decision: Pass Screening / Watchlist / Archive
- Primary reason:
- Main risk:
- Main thing to verify:

## If It Passes Screening
- Business Underwriting handoff 1:

## One-Page Screening Conclusion
- Next action:
""",
            },
        )
        company = db.create_company(self.conn, {"ticker": "OVS", "name": "Override Screening Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": stage_id, "template_id": template["id"]},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Override packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="override-screening.txt",
            file_content=b"Override packet",
            file_mime_type="text/plain",
        )
        section_ids = {section["title"]: section["id"] for section in report["template"]["schema"]["sections"]}
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }
        override_field_id = fields[("Final Decision", "Override rationale")]
        base_payload = {
            "responses": {
                fields[("Hard Gate Summary", "Operating history - Result")]: "Watchlist",
                fields[("Hard Gate Summary", "Operating history - Main Note")]: "The evidence base is still thin enough to justify caution.",
                fields[("Hard Gate Summary", "Munger checks - Result")]: "Needs Verification",
                fields[("Hard Gate Summary", "Munger checks - Main Note")]: "The outside view is still incomplete at this stage.",
                fields[("Final Decision", "Decision")]: "Pass Screening",
                fields[("Final Decision", "Primary reason")]: "The idea remains actionable despite one bounded unresolved issue.",
                fields[("Final Decision", "Main risk")]: "Evidence could still prove the operating record too thin.",
                fields[("Final Decision", "Main thing to verify")]: "Confirm the next filing resolves the remaining uncertainty.",
                fields[("If It Passes Screening", "Business Underwriting handoff 1")]: "Test operating history and stress evidence first.",
                fields[("One-Page Screening Conclusion", "Next action")]: "Advance only with a documented override.",
            },
            "field_sources": {
                f"section:{section_ids['Hard Gate Summary']}": {"source_ids": [source["id"]], "citation": "override packet"},
                f"section:{section_ids['Final Decision']}": {"source_ids": [source["id"]], "citation": "override packet"},
                f"section:{section_ids['If It Passes Screening']}": {"source_ids": [source["id"]], "citation": "override packet"},
                f"section:{section_ids['One-Page Screening Conclusion']}": {"source_ids": [source["id"]], "citation": "override packet"},
            },
            "field_notes": self.required_field_notes(
                report,
                [
                    fields[("Hard Gate Summary", "Operating history - Result")],
                    fields[("Hard Gate Summary", "Munger checks - Result")],
                    fields[("Final Decision", "Decision")],
                ],
            ),
        }

        with self.assertRaises(db.ReportCompletionBlocked) as ctx:
            self.update_report(report["id"], {"finalize": True, **base_payload})

        self.assertIn("override rationale", " ".join(ctx.exception.completion["decision_requirements"]).lower())

        updated = self.update_report(
            report["id"],
            {
                "finalize": True,
                **base_payload,
                "responses": {
                    **base_payload["responses"],
                    override_field_id: self.strict_override_rationale(),
                },
            },
        )

        self.assertEqual(updated["result"], db.RESULT_PROCEED)
        self.assertEqual(updated["completion"]["status"], "complete")

    def test_hard_gate_archive_requires_override_when_final_decision_is_softer(self) -> None:
        stage_id = self.stage_id("business_underwriting")
        template = db.save_template(
            self.conn,
            {
                "stage_id": stage_id,
                "name": "Mini Business Override Template",
                "description": "Generic hard-gate override checks.",
                "markdown": """
# Mini Business Override Template

## Facts
**Core fact**:

## Hard Gate Summary
| Hard Gate | Result | Main Note |
| --- | --- | --- |
| Accounting discipline | Pass / Watchlist / Archive |  |

## Final Decision
- Decision: Pass Business Underwriting / Watchlist / Archive
- Primary reason:
- Main risk:

## If It Goes To Watchlist
- Watchlist trigger:
""",
            },
        )
        company = db.create_company(self.conn, {"ticker": "OVB", "name": "Override Business Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": stage_id, "template_id": template["id"]},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Business override packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="override-business.txt",
            file_content=b"Business override packet",
            file_mime_type="text/plain",
        )
        section_ids = {section["title"]: section["id"] for section in report["template"]["schema"]["sections"]}
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }
        override_field_id = fields[("Final Decision", "Override rationale")]
        base_payload = {
            "responses": {
                fields[("Facts", "Core fact")]: "The business still appears understandable.",
                fields[("Hard Gate Summary", "Accounting discipline - Result")]: "Archive",
                fields[("Hard Gate Summary", "Accounting discipline - Main Note")]: "The accounting issue is severe enough that a softer decision needs an explicit override.",
                fields[("Final Decision", "Decision")]: "Watchlist",
                fields[("Final Decision", "Primary reason")]: "Need more time before rejecting the idea outright.",
                fields[("Final Decision", "Main risk")]: "The accounting concern may prove structural.",
                fields[("If It Goes To Watchlist", "Watchlist trigger")]: "Only revisit if the accounting issue is disproved.",
            },
            "review_date": "2026-08-01",
            "watchlist_objective_rules": [
                {
                    "metric_name": "Accounting issue disproved",
                    "comparator": "=",
                    "threshold_value": 1,
                    "unit": "event",
                }
            ],
            "field_sources": {
                f"section:{section_ids['Facts']}": {"source_ids": [source["id"]], "citation": "business override packet"},
                f"section:{section_ids['Hard Gate Summary']}": {"source_ids": [source["id"]], "citation": "business override packet"},
                f"section:{section_ids['Final Decision']}": {"source_ids": [source["id"]], "citation": "business override packet"},
                f"section:{section_ids['If It Goes To Watchlist']}": {"source_ids": [source["id"]], "citation": "business override packet"},
            },
            "field_notes": self.required_field_notes(
                report,
                [
                    fields[("Hard Gate Summary", "Accounting discipline - Result")],
                    fields[("Final Decision", "Decision")],
                ],
            ),
        }

        with self.assertRaises(db.ReportCompletionBlocked) as ctx:
            self.update_report(report["id"], {"finalize": True, **base_payload})

        self.assertIn("override rationale", " ".join(ctx.exception.completion["decision_requirements"]).lower())

        updated = self.update_report(
            report["id"],
            {
                "finalize": True,
                **base_payload,
                "responses": {
                    **base_payload["responses"],
                    override_field_id: self.strict_override_rationale(),
                },
            },
        )

        self.assertEqual(updated["result"], db.RESULT_WATCHLIST)
        self.assertEqual(updated["completion"]["status"], "complete")

    def test_all_stage_reports_expose_agent_contract(self) -> None:
        company = db.create_company(self.conn, {"ticker": "ALL", "name": "All Stages Corp"})

        for stage in db.list_stages(self.conn):
            report = db.create_report(
                self.conn,
                {"company_id": company["id"], "stage_id": stage["id"], "title": f"{stage['name']} draft"},
            )
            contract = report["agent_contract"]

            self.assertEqual(contract["report_kind"], stage["key"])
            self.assertTrue(contract["fillable_sections"])
            self.assertEqual(contract["workflow"]["current_stage"]["key"], stage["key"])
            self.assertIn("completion", contract)
            if stage["key"] == "execution_rules":
                self.assertIsNone(contract["workflow"]["next_stage"])
            else:
                self.assertIsNotNone(contract["workflow"]["next_stage"])

    def test_business_underwriting_report_exposes_generic_agent_contract_and_workflow_context(self) -> None:
        company = db.create_company(self.conn, {"ticker": "BUS", "name": "Business Workflow Corp"})
        screening = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        db.update_report(
            self.conn,
            screening["id"],
            {
                "result": db.RESULT_PROCEED,
                "summary": "Screening passed.",
            },
        )

        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "Business underwriting packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="business.txt",
            file_content=b"Business underwriting packet",
            file_mime_type="text/plain",
        )
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }
        responses = {
            fields[("Part I. Screening Handoff And Delta Thesis", "Result")]: "Clear",
            fields[("3. Evidence Read", "Evidence Result")]: "Adequate",
            fields[("1. Market Boundary", "Result")]: "Clear",
            fields[("2. Value Chain And Profit Pool", "Result")]: "Clear",
            fields[("Final Decision", "Primary reason")]: "Business quality clears the bar.",
            fields[("Final Decision", "Main business strength")]: "Recurring demand and pricing power.",
            fields[("Final Decision", "Main business weakness")]: "Customer concentration.",
            fields[("Final Decision", "Main thing to verify")]: "Validate retention against cohort disclosures.",
            fields[("Final Decision", "Decision")]: "Pass Business Underwriting",
        }
        updated = db.update_report(
            self.conn,
            report["id"],
            {
                "responses": responses,
                "field_sources": {
                    field_id: {"source_ids": [source["id"]], "citation": "primary packet"}
                    for field_id in responses
                },
            },
        )

        contract = updated["agent_contract"]
        self.assertEqual(updated["result"], db.RESULT_PROCEED)
        self.assertIn("Decision: Pass Business Underwriting", updated["summary"])
        self.assertIn("Primary reason: Business quality clears the bar.", updated["summary"])
        self.assertEqual(contract["report_kind"], "business_underwriting")
        self.assertEqual(contract["completion"]["status"], "in_progress")
        self.assertEqual(contract["workflow"]["previous_reports"][0]["stage_key"], "screening")
        self.assertEqual(contract["workflow"]["next_stage"]["key"], "management_underwriting")
        self.assertTrue(any(resource["kind"] == "workflow_report" for resource in contract["resources"]))
        self.assertTrue(any(resource["kind"] == "report_source" for resource in contract["resources"]))

    def test_management_underwriting_contract_marks_latest_handoffs_and_suggested_sources(self) -> None:
        company = db.create_company(self.conn, {"ticker": "MGC", "name": "Management Canonical Corp"})
        screening_old = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening"), "title": "Screening old"},
        )
        db.update_report(
            self.conn,
            screening_old["id"],
            {"result": db.RESULT_PROCEED, "summary": "Older screening handoff."},
        )
        screening_new = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening"), "title": "Screening new"},
        )
        db.update_report(
            self.conn,
            screening_new["id"],
            {"result": db.RESULT_PROCEED, "summary": "Newer screening handoff."},
        )

        business = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        business_source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            business["id"],
            {
                "title": "Business cited packet",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
            },
            file_name="business.txt",
            file_content=b"Business cited packet",
            file_mime_type="text/plain",
        )
        business_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in business["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            business["id"],
            {
                "responses": {
                    business_fields[("Final Decision", "Decision")]: "Pass Business Underwriting",
                },
                "summary": "Business handoff.",
                "field_sources": {
                    business_fields[("Final Decision", "Decision")]: {
                        "source_ids": [business_source["id"]],
                        "citation": "primary management handoff evidence",
                    }
                },
            },
        )

        management = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("management_underwriting")},
        )
        workflow = management["workflow"]
        screening_history = [item for item in workflow["previous_reports"] if item["stage_key"] == "screening"]

        self.assertEqual(len(screening_history), 2)
        self.assertTrue(screening_history[0]["is_latest_for_stage"])
        self.assertFalse(screening_history[1]["is_latest_for_stage"])
        self.assertEqual(
            [item["stage_key"] for item in workflow["latest_previous_reports"]],
            ["screening", "business_underwriting"],
        )
        self.assertEqual(workflow["latest_upstream_report"]["id"], business["id"])

        contract = management["agent_contract"]
        self.assertTrue(contract["suggested_sources"])
        self.assertEqual(contract["suggested_sources"][0]["id"], business_source["id"])
        self.assertEqual(
            contract["suggested_sources"][0]["suggestion_reason"],
            "cited_in_latest_upstream_report",
        )
        self.assertEqual(contract["suggested_sources"][0]["stage_key"], "business_underwriting")

        source_resource = next(
            resource
            for resource in contract["resources"]
            if resource["kind"] == "report_source" and resource["annotations"]["source_id"] == business_source["id"]
        )
        self.assertTrue(source_resource["annotations"]["suggested_for_reuse"])
        self.assertEqual(
            source_resource["annotations"]["suggestion_reason"],
            "cited_in_latest_upstream_report",
        )
        self.assertEqual(source_resource["annotations"]["stage_key"], "business_underwriting")

        workflow_resource = next(
            resource
            for resource in contract["resources"]
            if resource["kind"] == "workflow_report" and resource["annotations"]["stage_key"] == "business_underwriting"
        )
        self.assertTrue(workflow_resource["annotations"]["is_latest_for_stage"])

    def test_business_underwriting_auto_inherits_relevant_screening_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "AUT", "name": "Auto Handoff Corp"})
        screening = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        screening_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in screening["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            screening["id"],
            {
                "responses": {
                    screening_fields[("Basic Inputs", "Company")]: "Auto Handoff Corp",
                    screening_fields[("Basic Inputs", "Ticker")]: "AUT",
                    screening_fields[("Basic Inputs", "Date")]: "2026-04-18",
                    screening_fields[("Basic Inputs", "Analyst")]: "Diego",
                    screening_fields[("Basic Inputs", "Fiscal year-end")]: "2026-12-31",
                    screening_fields[("Basic Inputs", "Primary sources reviewed")]: "Annual report, investor day.",
                    screening_fields[("Basic Inputs", "Competitor filings reviewed")]: "Peer 10-K set.",
                    screening_fields[("Basic Inputs", "Other sources reviewed")]: "Industry deck.",
                    screening_fields[("Moat Hypothesis", "What is the moat? Do not name a moat type without evidence.")]: "Route density and switching costs.",
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                    screening_fields[("Final Decision", "Business category")]: "Good Predictable",
                    screening_fields[("Final Decision", "Main risk")]: "Channel concentration.",
                    screening_fields[("Final Decision", "Main thing to verify")]: "Retention by cohort.",
                    screening_fields[("One-Page Screening Conclusion", "Why this might be interesting")]: "High-quality niche leader.",
                    screening_fields[("One-Page Screening Conclusion", "Main disconfirming evidence")]: "Private-label risk.",
                    screening_fields[("One-Page Screening Conclusion", "Downstream issues to preserve")]: "Validate retention, margin durability, and buy rules.",
                }
            },
        )

        business = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        business_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in business["template"]["schema"]["fields"]
        }

        self.assertEqual(business["inherited_screening"]["report_id"], screening["id"])
        self.assertEqual(
            business["responses"][business_fields[("Inherited From Screening", "Company")]],
            "Auto Handoff Corp",
        )
        self.assertEqual(
            business["responses"][business_fields[("Inherited From Screening", "Main moat hypothesis inherited from screening")]],
            "Route density and switching costs.",
        )
        self.assertEqual(
            business["responses"][business_fields[("Inherited From Screening", "Main business uncertainty left open by screening")]],
            "Retention by cohort.",
        )
        self.assertEqual(
            business["responses"][business_fields[("Inherited From Screening", "Main downstream issues already parked for later stages")]],
            "Validate retention, margin durability, and buy rules.",
        )
        self.assertEqual(
            business["responses"][business_fields[("Inherited From Screening", "External business evidence reviewed")]],
            "Primary sources reviewed: Annual report, investor day.; Competitor filings reviewed: Peer 10-K set.; Other sources reviewed: Industry deck.",
        )
        self.assertIn(
            business_fields[("Inherited From Screening", "Company")],
            business["auto_inherited_fields"],
        )

        editable_field = next(
            field
            for field in business["template"]["schema"]["fields"]
            if field["id"] not in business["auto_inherited_fields"] and field["kind"] not in {"metric", "number"}
        )
        db.update_report(
            self.conn,
            business["id"],
            {
                "responses": {
                    editable_field["id"]: "Manual downstream note.",
                }
            },
        )

        db.update_report(
            self.conn,
            screening["id"],
            {
                "responses": {
                    screening_fields[("Final Decision", "Main risk")]: "Customer concentration instead of channel concentration.",
                }
            },
        )
        refreshed = db.get_report(self.conn, business["id"])
        self.assertEqual(
            refreshed["responses"][business_fields[("Inherited From Screening", "Main business downside inherited from screening")]],
            "Customer concentration instead of channel concentration.",
        )
        stored = self.conn.execute(
            "SELECT responses_json FROM reports WHERE id = ?",
            (business["id"],),
        ).fetchone()
        self.assertIsNotNone(stored)
        persisted_responses = json.loads(stored["responses_json"] or "{}")
        self.assertNotIn(
            business_fields[("Inherited From Screening", "Main business downside inherited from screening")],
            persisted_responses,
        )

    def test_management_underwriting_auto_inherits_relevant_business_and_screening_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "MGT", "name": "Management Inherit Corp"})
        screening = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        screening_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in screening["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            screening["id"],
            {
                "responses": {
                    screening_fields[("Basic Inputs", "Company")]: "Management Inherit Corp",
                    screening_fields[("Basic Inputs", "Ticker")]: "MGT",
                    screening_fields[("Basic Inputs", "Date")]: "2026-04-18",
                    screening_fields[("Basic Inputs", "Analyst")]: "Diego",
                    screening_fields[("Moat Hypothesis", "What is the moat? Do not name a moat type without evidence.")]: "Distribution density and switching costs.",
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                    screening_fields[("Final Decision", "Main risk")]: "Channel concentration.",
                    screening_fields[("Final Decision", "Main thing to verify")]: "Retention by cohort.",
                    screening_fields[("If It Passes Screening", "Management Underwriting issue")]: "Assess capital allocation discipline and candor.",
                    screening_fields[("One-Page Screening Conclusion", "Why this might be interesting")]: "A niche compounder with defendable economics.",
                    screening_fields[("One-Page Screening Conclusion", "Downstream issues to preserve")]: "Management, financial normalization, valuation triggers.",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        business = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        business_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in business["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            business["id"],
            {
                "responses": {
                    business_fields[("Final Decision", "Decision")]: "Pass Business Underwriting",
                    business_fields[("Final Decision", "Business type")]: "Good Predictable",
                    business_fields[("Final Decision", "Primary reason")]: "Durable unit economics with real local advantage.",
                    business_fields[("Final Decision", "Main business weakness")]: "Execution still matters in a concentrated channel.",
                    business_fields[("Final Decision", "Main thing to verify")]: "Whether discipline survives weaker periods.",
                    business_fields[("Final Decision", "Main question for Management Underwriting")]: "Does management allocate capital with per-share discipline?",
                    business_fields[("Final Decision", "Main question for Financial Underwriting")]: "How much of reported earnings convert to owner earnings?",
                    business_fields[("Final Decision", "Main question for Valuation and Position Size")]: "How cyclical are normalized margins?",
                    business_fields[("If It Passes Business Underwriting", "Financial Underwriting issue")]: "Validate cash conversion and working-capital quality.",
                    business_fields[("If It Passes Business Underwriting", "Valuation and Position Size issue")]: "Stress-test the normalized margin assumption.",
                    business_fields[("If It Passes Business Underwriting", "Execution Rules issue")]: "Define a price trigger before entry.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Date")]: "2026-04-19",
                    business_fields[("One-Page Business Underwriting Conclusion", "Screening claim tested")]: "The business can sustain superior economics beyond the current cycle.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Primary source of advantage")]: "Distribution density reinforced by switching costs.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Unit-economics read")]: "High gross profit per customer with low incremental service cost.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Economic-goodwill / capital-intensity read")]: "Low tangible capital needs with meaningful intangible reinvestment.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Main disconfirming evidence")]: "Customer concentration could weaken pricing power.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Main Management Underwriting task")]: "Pressure-test management candor, capital allocation, and incentives.",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        management = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("management_underwriting")},
        )
        management_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in management["template"]["schema"]["fields"]
        }

        self.assertIsNotNone(management["inherited_business_underwriting"])
        self.assertEqual(management["inherited_business_underwriting"]["report_id"], business["id"])
        self.assertEqual(
            management["responses"][management_fields[("Inherited From Business Underwriting", "Company")]],
            "Management Inherit Corp",
        )
        self.assertEqual(
            management["responses"][management_fields[("Inherited From Business Underwriting", "Main question handed to Management Underwriting")]],
            "Does management allocate capital with per-share discipline?",
        )
        self.assertIn(
            "Financial Underwriting issue: Validate cash conversion and working-capital quality.",
            management["responses"][management_fields[("Inherited From Business Underwriting", "Main downstream issues already parked for later stages")]],
        )
        self.assertEqual(
            management["responses"][management_fields[("Part I. Business Handoff And Delta Thesis", "Which exact management claim from Business Underwriting is being tested now?")]],
            "Does management allocate capital with per-share discipline?",
        )
        self.assertIn(
            management_fields[("Part I. Business Handoff And Delta Thesis", "Which exact management claim from Business Underwriting is being tested now?")],
            management["auto_inherited_fields"],
        )
        self.assertIn(
            management_fields[("Part I. Business Handoff And Delta Thesis", "Which exact management claim from Business Underwriting is being tested now?")],
            management["agent_contract"]["readonly_field_ids"],
        )
        self.assertIn(
            "Business claim: The business can sustain superior economics beyond the current cycle.",
            management["responses"][management_fields[("Part I. Business Handoff And Delta Thesis", "What business facts are already considered proved and should not be re-underwritten here?")]],
        )

    def test_financial_underwriting_auto_inherits_relevant_management_business_and_screening_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "FIN", "name": "Financial Inherit Corp"})
        screening = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        screening_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in screening["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            screening["id"],
            {
                "responses": {
                    screening_fields[("Basic Inputs", "Company")]: "Financial Inherit Corp",
                    screening_fields[("Basic Inputs", "Ticker")]: "FIN",
                    screening_fields[("Basic Inputs", "Date")]: "2026-04-18",
                    screening_fields[("Basic Inputs", "Analyst")]: "Diego",
                    screening_fields[("If It Passes Screening", "Financial Underwriting issue")]: "Prove owner earnings and balance-sheet resilience.",
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                    screening_fields[("Final Decision", "Main risk")]: "Leverage could bite in a downturn.",
                    screening_fields[("Final Decision", "Main thing to verify")]: "How much of working-capital cash flow is structural.",
                    screening_fields[("One-Page Screening Conclusion", "Downstream issues to preserve")]: "Financial normalization and balance-sheet stress work remain open.",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        business = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        business_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in business["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            business["id"],
            {
                "responses": {
                    business_fields[("Final Decision", "Decision")]: "Pass Business Underwriting",
                    business_fields[("Final Decision", "Business type")]: "Good Predictable",
                    business_fields[("Final Decision", "Main question for Financial Underwriting")]: "How much of reported earnings convert to owner earnings after maintenance capex?",
                    business_fields[("If It Passes Business Underwriting", "Financial Underwriting issue")]: "Check working-capital quality and hidden financing.",
                    business_fields[("If It Passes Business Underwriting", "Valuation and Position Size issue")]: "Use a conservative normalized owner-earnings range.",
                    business_fields[("If It Passes Business Underwriting", "Execution Rules issue")]: "Do not buy until the normalization range is trusted.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Date")]: "2026-04-19",
                    business_fields[("One-Page Business Underwriting Conclusion", "Why customers buy and stay")]: "Customers stay for reliability and switching friction.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Unit-economics read")]: "Healthy contribution economics with sticky repeat demand.",
                    business_fields[("One-Page Business Underwriting Conclusion", "Economic-goodwill / capital-intensity read")]: "Modest tangible capital needs relative to cash generation.",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        management = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("management_underwriting")},
        )
        management_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in management["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            management["id"],
            {
                "responses": {
                    management_fields[("Final Decision", "Decision")]: "Pass Management Underwriting",
                    management_fields[("Final Decision", "Main Financial Underwriting task")]: "Test owner earnings, dilution, and balance-sheet survivability conservatively.",
                    management_fields[("Final Decision", "Main risk")]: "Management may overstate normalized cash generation.",
                    management_fields[("If It Passes Management Underwriting", "Financial Underwriting issue")]: "Reconcile stock compensation, owner earnings, and share-count discipline.",
                    management_fields[("If It Passes Management Underwriting", "Valuation and Position Size issue")]: "Only value normalized owner earnings after conservative adjustments.",
                    management_fields[("If It Passes Management Underwriting", "Execution Rules issue")]: "Wait for clean quarterly cash conversion before acting.",
                    management_fields[("One-Page Management Conclusion", "Capital-allocation quick read")]: "Buybacks and reinvestment have generally favored per-share value.",
                    management_fields[("One-Page Management Conclusion", "Incentive quick read")]: "Compensation is acceptable but stock compensation still needs scrutiny.",
                    management_fields[("One-Page Management Conclusion", "Governance or control quick read")]: "Governance is adequate with no obvious control abuse.",
                    management_fields[("One-Page Management Conclusion", "Why this management might destroy value")]: "Aggressive adjustment culture could spill into the financial story.",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        financial = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("financial_underwriting")},
        )
        financial_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in financial["template"]["schema"]["fields"]
        }

        self.assertIsNotNone(financial["inherited_management_underwriting"])
        self.assertEqual(financial["inherited_management_underwriting"]["report_id"], management["id"])
        self.assertEqual(
            financial["responses"][financial_fields[("Inherited From Management Underwriting", "Company")]],
            "Financial Inherit Corp",
        )
        self.assertEqual(
            financial["responses"][financial_fields[("Inherited From Management Underwriting", "Main financial question handed to this stage")]],
            "Test owner earnings, dilution, and balance-sheet survivability conservatively.",
        )
        self.assertIn(
            "Capital allocation: Buybacks and reinvestment have generally favored per-share value.",
            financial["responses"][financial_fields[("Inherited From Management Underwriting", "Capital-allocation, dilution, and governance read inherited from Management Underwriting")]],
        )
        self.assertIn(
            "Valuation and Position Size issue: Only value normalized owner earnings after conservative adjustments.",
            financial["responses"][financial_fields[("Inherited From Management Underwriting", "Main downstream issues already parked for later stages")]],
        )
        self.assertEqual(
            financial["responses"][financial_fields[("Part I. Management Handoff And Delta Thesis", "Which exact financial claim from Screening, Business Underwriting, or Management Underwriting is being tested now?")]],
            "Test owner earnings, dilution, and balance-sheet survivability conservatively.",
        )
        self.assertIn(
            financial_fields[("Part I. Management Handoff And Delta Thesis", "Which exact financial claim from Screening, Business Underwriting, or Management Underwriting is being tested now?")],
            financial["auto_inherited_fields"],
        )
        self.assertIn(
            financial_fields[("Part I. Management Handoff And Delta Thesis", "Which exact financial claim from Screening, Business Underwriting, or Management Underwriting is being tested now?")],
            financial["agent_contract"]["readonly_field_ids"],
        )

    def test_valuation_position_size_auto_inherits_relevant_financial_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "VAL", "name": "Valuation Inherit Corp"})
        financial = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("financial_underwriting")},
        )
        financial_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in financial["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            financial["id"],
            {
                "responses": {
                    financial_fields[("Inherited From Management Underwriting", "Company")]: "Valuation Inherit Corp",
                    financial_fields[("Inherited From Management Underwriting", "Ticker")]: "VAL",
                    financial_fields[("Inherited From Management Underwriting", "Date")]: "2026-04-18",
                    financial_fields[("Inherited From Management Underwriting", "Analyst")]: "Diego",
                    financial_fields[("Inherited From Management Underwriting", "Capital-allocation, dilution, and governance read inherited from Management Underwriting")]: "Capital allocation and dilution discipline look acceptable so far.",
                    financial_fields[("Basic Inputs", "Date")]: "2026-04-20",
                    financial_fields[("Basic Inputs", "Analyst")]: "Diego",
                    financial_fields[("Basic Inputs", "Financial model or worksheet used")]: "Owner-earnings model v3",
                    financial_fields[("7. Normalization Bridge", "Rough normalized tax rate")]: "24%",
                    financial_fields[("If It Passes Financial Underwriting", "Business Underwriting handoff 1")]: "Translate the normalized owner-earnings range into a conservative price ladder.",
                    financial_fields[("If It Passes Financial Underwriting", "Execution Rules issue")]: "Respect liquidity and avoid chasing above the starter range.",
                    financial_fields[("Final Decision", "Decision")]: "Pass Financial Underwriting",
                    financial_fields[("Final Decision", "Financial pattern")]: "Good Predictable",
                    financial_fields[("Final Decision", "Main permanent-loss risk")]: "If normalized cash conversion proves overstated, the valuation collapses.",
                    financial_fields[("Final Decision", "Main thing to verify")]: "Whether working-capital releases are structural or temporary.",
                    financial_fields[("Final Decision", "What valuation can safely assume")]: "Base owner earnings are achievable without multiple expansion.",
                    financial_fields[("Final Decision", "What valuation must not assume")]: "No heroic margin expansion or aggressive buybacks.",
                    financial_fields[("One-Page Financial Underwriting Conclusion", "Date")]: "2026-04-20",
                    financial_fields[("One-Page Financial Underwriting Conclusion", "Main Valuation and Position Size task")]: "Convert normalized owner earnings into a conservative worth range and price ladder.",
                    financial_fields[("One-Page Financial Underwriting Conclusion", "Returns on capital view")]: "Returns are good enough without leverage doing all the work.",
                    financial_fields[("One-Page Financial Underwriting Conclusion", "Balance sheet view")]: "Balance sheet can absorb a bad year without forced dilution.",
                    financial_fields[("One-Page Financial Underwriting Conclusion", "Per-share value-creation view")]: "Per-share value creation looks favorable with dilution contained.",
                },
                "metrics": {
                    financial_fields[("Basic Inputs", "Current share price")]: "72",
                    financial_fields[("Basic Inputs", "Diluted shares")]: "100",
                    financial_fields[("Basic Inputs", "Market capitalization")]: "7200",
                    financial_fields[("Basic Inputs", "Net debt / net cash")]: "-250",
                    financial_fields[("Basic Inputs", "Enterprise value")]: "6950",
                    financial_fields[("7. Normalization Bridge", "Low normalized owner earnings")]: "420",
                    financial_fields[("7. Normalization Bridge", "Base normalized owner earnings")]: "500",
                    financial_fields[("7. Normalization Bridge", "High normalized owner earnings")]: "560",
                    financial_fields[("7. Normalization Bridge", "Rough normalized maintenance capex")]: "85",
                    financial_fields[("7. Normalization Bridge", "Rough normalized working-capital need")]: "20",
                    financial_fields[("2. Owner Earnings Worksheet", "Owner earnings per share")]: "5.00",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        valuation = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("valuation_position_size")},
        )
        valuation_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in valuation["template"]["schema"]["fields"]
        }

        self.assertIsNotNone(valuation["inherited_financial_underwriting"])
        self.assertEqual(valuation["inherited_financial_underwriting"]["report_id"], financial["id"])
        self.assertEqual(
            valuation["responses"][valuation_fields[("Inherited From Financial Underwriting", "Company")]],
            "Valuation Inherit Corp",
        )
        self.assertEqual(
            valuation["responses"][valuation_fields[("Inherited From Financial Underwriting", "Main valuation question handed to this stage")]],
            "Convert normalized owner earnings into a conservative worth range and price ladder.",
        )
        self.assertEqual(
            valuation["responses"][valuation_fields[("Inherited From Financial Underwriting", "Primary valuation method expected")]],
            "Owner earnings / earning power",
        )
        self.assertEqual(
            valuation["responses"][valuation_fields[("1. Imported Economics From Financial Underwriting", "Base normalized owner earnings inherited")]],
            "500",
        )
        self.assertEqual(
            valuation["responses"][valuation_fields[("Part I. Financial Handoff And Valuation Delta Thesis", "Which exact valuation question from Financial Underwriting is being solved now?")]],
            "Convert normalized owner earnings into a conservative worth range and price ladder.",
        )
        self.assertIn(
            valuation_fields[("Part I. Financial Handoff And Valuation Delta Thesis", "Which exact valuation question from Financial Underwriting is being solved now?")],
            valuation["auto_inherited_fields"],
        )
        self.assertIn(
            valuation_fields[("Part I. Financial Handoff And Valuation Delta Thesis", "Which exact valuation question from Financial Underwriting is being solved now?")],
            valuation["agent_contract"]["readonly_field_ids"],
        )

    def test_valuation_return_to_underwriting_routes_company_back_to_selected_stage(self) -> None:
        company = db.create_company(self.conn, {"ticker": "RTU", "name": "Return Underwriting Corp"})
        valuation = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("valuation_position_size")},
        )
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in valuation["template"]["schema"]["fields"]
        }

        updated = db.update_report(
            self.conn,
            valuation["id"],
            {
                "responses": {
                    fields[("Final Decision", "Decision")]: "Return To Underwriting",
                    fields[("If It Returns To Underwriting", "Return reason")]: "The normalized owner-earnings range still depends on an unproven working-capital release.",
                    fields[("If It Returns To Underwriting", "Correct stage")]: "Financial Underwriting",
                    fields[("If It Returns To Underwriting", "Immediate next checklist or memo")]: "Rebuild the cash-conversion memo using a conservative working-capital view.",
                    fields[("If It Returns To Underwriting", "Specific assumption that cannot be trusted today")]: "Working-capital normalization.",
                },
            },
        )

        refreshed_company = db.get_company(self.conn, company["id"])
        self.assertEqual(updated["result"], db.RESULT_RETURN_FINANCIAL)
        self.assertEqual(refreshed_company["current_stage_key"], "financial_underwriting")

    def test_execution_rules_auto_inherits_relevant_valuation_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "EXE", "name": "Execution Inherit Corp"})
        valuation = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("valuation_position_size")},
        )
        valuation_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in valuation["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            valuation["id"],
            {
                "responses": {
                    valuation_fields[("Inherited From Financial Underwriting", "Company")]: "Execution Inherit Corp",
                    valuation_fields[("Inherited From Financial Underwriting", "Ticker")]: "EXE",
                    valuation_fields[("Inherited From Financial Underwriting", "Date")]: "2026-04-18",
                    valuation_fields[("Inherited From Financial Underwriting", "Analyst")]: "Diego",
                    valuation_fields[("Inherited From Financial Underwriting", "Diluted share count inherited")]: "120",
                    valuation_fields[("Inherited From Financial Underwriting", "Current best alternative use of capital")]: "A smaller add to an existing high-conviction holding.",
                    valuation_fields[("If It Is Approved For Execution", "Attractive / starter buy range")]: "$64-$68",
                    valuation_fields[("If It Is Approved For Execution", "Clearly cheap enough to size up")]: "$58",
                    valuation_fields[("If It Is Approved For Execution", "No-buy above")]: "$72",
                    valuation_fields[("If It Is Approved For Execution", "Starter size")]: "2.5%",
                    valuation_fields[("If It Is Approved For Execution", "Return To Underwriting conditions")]: "If working-capital normalization slips again, reopen valuation before buying more.",
                    valuation_fields[("If It Is Approved For Execution", "Liquidity / order-type considerations")]: "Use patient limits and avoid the open in the ADR.",
                    valuation_fields[("Final Decision", "Decision")]: "Approve For Execution",
                    valuation_fields[("Final Decision", "Conservative worth per share")]: "80",
                    valuation_fields[("Final Decision", "Base worth per share")]: "92",
                    valuation_fields[("Final Decision", "High worth per share")]: "104",
                    valuation_fields[("Final Decision", "Hard maximum weight")]: "6%",
                    valuation_fields[("Final Decision", "Opportunity cost")]: "Capital is available, but there is a credible alternative idea.",
                    valuation_fields[("Final Decision", "Main risk")]: "If normalized cash conversion is overstated, downside is worse than it looks.",
                    valuation_fields[("Final Decision", "Main thing to verify before buying")]: "Whether the latest quarter confirmed the cash-conversion bridge.",
                    valuation_fields[("One-Page Valuation And Position Size Conclusion", "Date")]: "2026-04-20",
                    valuation_fields[("One-Page Valuation And Position Size Conclusion", "Primary valuation method")]: "Owner earnings / earning power",
                    valuation_fields[("One-Page Valuation And Position Size Conclusion", "Expected return without rerating")]: "Low double-digit return at the current quote.",
                    valuation_fields[("One-Page Valuation And Position Size Conclusion", "Downside view")]: "Balance sheet is fine, but the normalized range still matters.",
                    valuation_fields[("One-Page Valuation And Position Size Conclusion", "What valuation can safely assume")]: "Current margins do not need to expand.",
                    valuation_fields[("One-Page Valuation And Position Size Conclusion", "What valuation must not assume")]: "No heroic buyback help.",
                },
                "metrics": {
                    valuation_fields[("Inherited From Financial Underwriting", "Current share price")]: "67",
                    valuation_fields[("Inherited From Financial Underwriting", "Current market capitalization")]: "8040",
                    valuation_fields[("Inherited From Financial Underwriting", "Current enterprise value")]: "7810",
                    valuation_fields[("Inherited From Financial Underwriting", "Net debt / net cash inherited")]: "-230",
                    valuation_fields[("Final Decision", "Current price")]: "67",
                    valuation_fields[("Inherited From Financial Underwriting", "Low normalized owner earnings inherited")]: "430",
                    valuation_fields[("Inherited From Financial Underwriting", "Base normalized owner earnings inherited")]: "510",
                    valuation_fields[("Inherited From Financial Underwriting", "High normalized owner earnings inherited")]: "575",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        execution = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("execution_rules")},
        )
        execution_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in execution["template"]["schema"]["fields"]
        }

        self.assertIsNotNone(execution["inherited_valuation_position_size"])
        self.assertEqual(execution["inherited_valuation_position_size"]["report_id"], valuation["id"])
        self.assertEqual(
            execution["responses"][execution_fields[("1. Master Snapshot Table", "Company - Value")]],
            "Execution Inherit Corp",
        )
        self.assertEqual(
            execution["responses"][execution_fields[("1. Master Snapshot Table", "Conservative worth per share - Value")]],
            "80",
        )
        self.assertEqual(
            execution["responses"][execution_fields[("Part I. Valuation Handoff And Execution Delta Thesis", "Which stage-5 conclusions are imported without rework?")]],
            "Decision: Approve For Execution; Conservative / base / high worth: 80 / 92 / 104; Starter range: $64-$68; Size-up price: $58; No-buy-above line: $72; Hard max: 6%",
        )
        self.assertEqual(
            execution["responses"][execution_fields[("6. Valuation Snapshot", "What primary valuation methods were used, and why do they fit the business?")]],
            "Owner earnings / earning power",
        )
        self.assertEqual(
            execution["responses"][execution_fields[("Final Decision", "Main fact that would stop buying")]],
            "Whether the latest quarter confirmed the cash-conversion bridge.",
        )
        self.assertIn(
            execution_fields[("1. Master Snapshot Table", "Company - Value")],
            execution["auto_inherited_fields"],
        )
        self.assertIn(
            execution_fields[("1. Master Snapshot Table", "Company - Value")],
            execution["agent_contract"]["readonly_field_ids"],
        )

    def test_execution_return_to_underwriting_routes_company_back_to_selected_stage(self) -> None:
        company = db.create_company(self.conn, {"ticker": "RTE", "name": "Execution Return Corp"})
        execution = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("execution_rules")},
        )
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in execution["template"]["schema"]["fields"]
        }

        updated = db.update_report(
            self.conn,
            execution["id"],
            {
                "responses": {
                    fields[("Final Decision", "Decision")]: "Return To Underwriting",
                    fields[("If It Returns To Underwriting", "Return reason")]: "The current quote no longer matches the valuation memo after a material share issuance.",
                    fields[("If It Returns To Underwriting", "Correct stage")]: "Valuation and Position Size",
                    fields[("If It Returns To Underwriting", "Immediate next checklist or memo")]: "Refresh the dilution bridge and rebuild the worth range before acting.",
                    fields[("If It Returns To Underwriting", "Specific assumption that cannot be trusted today")]: "Share-count stability.",
                },
            },
        )

        refreshed_company = db.get_company(self.conn, company["id"])
        self.assertEqual(updated["result"], db.RESULT_RETURN_VALUATION)
        self.assertEqual(refreshed_company["current_stage_key"], "valuation_position_size")

    def test_auto_inherited_business_fields_are_read_only_but_still_annotatable(self) -> None:
        company = db.create_company(self.conn, {"ticker": "ANN", "name": "Annotatable Handoff Corp"})
        screening = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        screening_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in screening["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            screening["id"],
            {
                "responses": {
                    screening_fields[("Basic Inputs", "Company")]: "Annotatable Handoff Corp",
                    screening_fields[("Basic Inputs", "Ticker")]: "ANN",
                    screening_fields[("Basic Inputs", "Date")]: "2026-04-18",
                    screening_fields[("Basic Inputs", "Analyst")]: "Diego",
                    screening_fields[("Final Decision", "Decision")]: "Pass Screening",
                    screening_fields[("Final Decision", "Main risk")]: "Customer concentration.",
                    screening_fields[("Final Decision", "Main thing to verify")]: "Retention by cohort.",
                    screening_fields[("One-Page Screening Conclusion", "Why this might be interesting")]: "Sticky customer relationships.",
                    screening_fields[("One-Page Screening Conclusion", "Downstream issues to preserve")]: "Retention, pricing power, and buy rules.",
                },
                "result": db.RESULT_PROCEED,
            },
        )

        business = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("business_underwriting")},
        )
        business_fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in business["template"]["schema"]["fields"]
        }
        inherited_field_id = business_fields[("Inherited From Screening", "Main business downside inherited from screening")]

        self.assertIn(inherited_field_id, business["auto_inherited_fields"])
        self.assertIn(inherited_field_id, business["agent_contract"]["readonly_field_ids"])

        inherited_summary = next(
            field
            for section in business["agent_contract"]["fillable_sections"]
            for field in section["fields"]
            if field["id"] == inherited_field_id
        )
        self.assertTrue(inherited_summary["read_only"])
        self.assertTrue(inherited_summary["annotations_allowed"])
        self.assertTrue(business["agent_contract"]["inherited_fields"]["annotations_allowed"])

        with self.assertRaisesRegex(ValueError, "Field is inherited and read-only"):
            db.update_report(
                self.conn,
                business["id"],
                {
                    "responses": {
                        inherited_field_id: "Manual overwrite.",
                    }
                },
            )

        source = self.save_report_source_ready(
            self.conn,
            self.uploads,
            business["id"],
            {
                "title": "Handoff memo",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "Medium",
                "notes": "Supports the inherited downside.",
            },
        )
        updated = db.update_report(
            self.conn,
            business["id"],
            {
                "field_sources": {
                    inherited_field_id: {
                        "source_ids": [source["id"]],
                        "citation": "Downside paragraph.",
                    }
                },
                "field_notes": {
                    inherited_field_id: "Carry this risk into the business review.",
                },
            },
        )

        self.assertEqual(
            updated["field_sources"][inherited_field_id]["source_ids"],
            [source["id"]],
        )
        self.assertEqual(
            updated["field_sources"][inherited_field_id]["citation"],
            "Downside paragraph.",
        )
        self.assertEqual(
            updated["field_notes"][inherited_field_id],
            "Carry this risk into the business review.",
        )

    def test_report_sources_and_field_links_are_persisted(self) -> None:
        company = db.create_company(self.conn, {"ticker": "SRC", "name": "Source Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        source = db.save_report_source(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "FY2025 annual report",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
                "tags": "filing,owner earnings",
                "url": "https://example.com/annual",
                "snapshot_guidance_acknowledged": True,
                "link_only_reason": "Snapshot upload deferred during the report draft; add a stored HTML export next.",
                "citation": "p. 234",
                "notes": "Primary filing.",
            },
        )
        template = report["template"]["schema"]
        field_id = db.get_section_field(template, "Basic Inputs", "Company")["id"]
        db.update_report(
            self.conn,
            report["id"],
            {
                "field_sources": {
                    field_id: {"source_ids": [source["id"]], "citation": "p. 234"}
                },
                "field_notes": {field_id: "Use the audited number only."},
            },
        )
        updated = db.get_report(self.conn, report["id"])
        revision_before_delete = int(updated["revision"])

        self.assertEqual(updated["sources"][0]["source_type"], "Annual report")
        self.assertEqual(updated["sources"][0]["tags"], ["filing", "owner earnings"])
        self.assertEqual(updated["field_sources"][field_id]["source_ids"], [source["id"]])
        self.assertEqual(updated["field_notes"][field_id], "Use the audited number only.")

        db.delete_report_source(self.conn, source["id"])
        updated = db.get_report(self.conn, report["id"])
        self.assertEqual(updated["sources"], [])
        self.assertEqual(updated["field_sources"][field_id]["source_ids"], [])
        self.assertEqual(updated["revision"], revision_before_delete + 1)

    def test_save_report_source_rolls_back_uploaded_document_on_validation_error(self) -> None:
        company = db.create_company(self.conn, {"ticker": "RBS", "name": "Rollback Source Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        with self.assertRaisesRegex(ValueError, "Invalid evidence grade"):
            db.save_report_source(
                self.conn,
                self.uploads,
                report["id"],
                {
                    "title": "Bad source",
                    "source_type": "Annual report",
                    "evidence_grade": "BAD",
                    "confidence": "High",
                    "notes": "Should not persist anything.",
                },
                file_name="bad-source.txt",
                file_content=b"payload",
                file_mime_type="text/plain",
                file_origin="uploaded_file",
            )

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM report_sources").fetchone()[0], 0)
        self.assertEqual([path for path in self.uploads.rglob("*") if path.is_file()], [])

    def test_partial_report_update_merges_existing_values(self) -> None:
        company = db.create_company(self.conn, {"ticker": "MRG", "name": "Merge Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in report["template"]["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            report["id"],
            {
                "responses": {
                    fields[("Final Decision", "Decision")]: "Watchlist",
                    fields[("Final Decision", "Primary reason")]: "Too expensive today.",
                    fields[("Final Decision", "Main risk")]: "Channel recovery may stall.",
                    fields[("Final Decision", "Main thing to verify")]: "Demand normalization.",
                    fields[("Final Decision", "Next funnel stage")]: "Business Underwriting",
                    fields[("Final Decision", "Review date, if Watchlist")]: "2026-06-01",
                    fields[("If It Goes To Watchlist", "Price")]: "Below $35.",
                    fields[("One-Page Screening Conclusion", "Next action")]: "Wait for a better entry point.",
                }
            },
        )

        updated = db.update_report(
            self.conn,
            report["id"],
            {
                "responses": {
                    fields[("Final Decision", "Decision")]: "Pass Screening",
                }
            },
        )

        self.assertEqual(updated["responses"][fields[("Final Decision", "Primary reason")]], "Too expensive today.")
        self.assertEqual(updated["responses"][fields[("Final Decision", "Main risk")]], "Channel recovery may stall.")
        self.assertIn("Primary reason: Too expensive today.", updated["summary"])
        self.assertEqual(updated["result"], db.RESULT_PROCEED)

    def test_report_revision_increments_on_successful_save(self) -> None:
        company = db.create_company(self.conn, {"ticker": "REVN", "name": "Revision Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        self.assertEqual(report["revision"], 1)

        updated = self.update_report(report["id"], {"summary": "First revision."})
        self.assertEqual(updated["revision"], 2)

    def test_report_revision_conflict_rejects_stale_write(self) -> None:
        company = db.create_company(self.conn, {"ticker": "STL", "name": "Stale Save Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})
        stale_revision = int(report["revision"])

        updated = self.update_report(report["id"], {"summary": "Fresh save."}, expected_revision=stale_revision)
        self.assertEqual(updated["revision"], stale_revision + 1)

        with self.assertRaises(db.ReportRevisionConflict):
            self.update_report(
                report["id"],
                {"summary": "Stale overwrite."},
                expected_revision=stale_revision,
            )

        preserved = db.get_report(self.conn, report["id"])
        self.assertEqual(preserved["summary"], "Fresh save.")
        self.assertEqual(preserved["revision"], stale_revision + 1)

    def test_update_report_rejects_unknown_field_ids(self) -> None:
        company = db.create_company(self.conn, {"ticker": "VAL", "name": "Validate Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )

        with self.assertRaises(ValueError):
            db.update_report(
                self.conn,
                report["id"],
                {"responses": {"not-a-real-field": "bad"}},
            )

    def test_report_source_patch_preserves_existing_metadata(self) -> None:
        company = db.create_company(self.conn, {"ticker": "RSP", "name": "Source Preserve Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        source = db.save_report_source(
            self.conn,
            self.uploads,
            report["id"],
            {
                "title": "FY2025 annual report",
                "source_type": "Annual report",
                "evidence_grade": "F",
                "confidence": "High",
                "tags": "filing,primary",
                "url": "https://example.com/annual",
                "snapshot_guidance_acknowledged": True,
                "link_only_reason": "Snapshot not uploaded yet; preserve the URL while waiting for the stored export.",
                "citation": "p. 1",
                "notes": "Original note.",
            },
        )
        updated = db.save_report_source(
            self.conn,
            self.uploads,
            report["id"],
            {
                "id": source["id"],
                "notes": "Updated note only.",
            },
        )

        self.assertEqual(updated["title"], "FY2025 annual report")
        self.assertEqual(updated["source_type"], "Annual report")
        self.assertEqual(updated["evidence_grade"], "F")
        self.assertEqual(updated["confidence"], "High")
        self.assertEqual(updated["citation"], "p. 1")
        self.assertEqual(updated["tags"], ["filing", "primary"])
        self.assertEqual(updated["notes"], "Updated note only.")

    def test_get_template_uses_stored_schema_snapshot(self) -> None:
        stage_id = self.stage_id("screening")
        row = self.conn.execute(
            "SELECT id FROM templates WHERE stage_id = ? AND is_active = 1 ORDER BY version DESC, id DESC LIMIT 1",
        (stage_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        template_id = int(row["id"])

        snapshot_schema = {
            "sections": [
                {
                    "id": "snapshot-section",
                    "title": "Stored Snapshot",
                    "fields": [
                        {
                            "id": "snapshot-field",
                            "label": "Snapshot field",
                            "kind": "text",
                        }
                    ],
                }
            ]
        }
        self.conn.execute("UPDATE templates SET schema_json = ? WHERE id = ?", (db.dump_json(snapshot_schema), template_id))
        self.conn.commit()

        template = db.get_template(self.conn, template_id)
        self.assertEqual(template["schema"]["field_count"], 1)
        self.assertEqual(template["schema"]["fields"][0]["label"], "Snapshot field")

    def test_list_templates_uses_stored_schema_snapshot(self) -> None:
        stage_id = self.stage_id("screening")
        row = self.conn.execute(
            "SELECT id FROM templates WHERE stage_id = ? AND is_active = 1 ORDER BY version DESC, id DESC LIMIT 1",
            (stage_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        template_id = int(row["id"])

        snapshot_schema = {
            "sections": [
                {
                    "id": "snapshot-section",
                    "title": "Stored Summary Snapshot",
                    "fields": [
                        {
                            "id": "snapshot-field",
                            "label": "Stored list field",
                            "kind": "text",
                        }
                    ],
                }
            ]
        }
        self.conn.execute("UPDATE templates SET schema_json = ? WHERE id = ?", (db.dump_json(snapshot_schema), template_id))
        self.conn.commit()

        templates = db.list_templates(self.conn)
        template = next(item for item in templates if item["id"] == template_id)
        self.assertEqual(template["schema"]["field_count"], 1)
        self.assertEqual(template["schema"]["fields"][0]["label"], "Stored list field")

    def test_get_template_falls_back_to_markdown_when_schema_snapshot_missing(self) -> None:
        stage_id = self.stage_id("screening")
        row = self.conn.execute(
            "SELECT id FROM templates WHERE stage_id = ? AND is_active = 1 ORDER BY version DESC, id DESC LIMIT 1",
            (stage_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        template_id = int(row["id"])

        markdown = "# Markdown Fallback Template\n\n## Parsed Section\n\n- Fallback field:\n"
        self.conn.execute(
            "UPDATE templates SET markdown = ?, schema_json = ? WHERE id = ?",
            (markdown, "{}", template_id),
        )
        self.conn.commit()

        template = db.get_template(self.conn, template_id)
        self.assertIn("Parsed Section", [section["title"] for section in template["schema"]["sections"]])
        self.assertEqual(template["schema"]["fields"][0]["label"], "Fallback field")

    def test_get_company_returns_report_summaries_only(self) -> None:
        company = db.create_company(self.conn, {"ticker": "SUM", "name": "Summary Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"]})

        company = db.get_company(self.conn, company["id"])
        self.assertEqual(len(company["reports"]), 1)
        self.assertEqual(
            set(company["reports"][0]),
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
        self.assertEqual(company["reports"][0]["id"], report["id"])
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
            self.assertNotIn(removed_key, company["reports"][0])

    def test_get_report_query_budgets(self) -> None:
        budgets = {
            "data_collection": 10,
            "screening": 11,
            "business_underwriting": 18,
            "management_underwriting": 18,
            "financial_underwriting": 18,
        }
        for stage_key, budget in budgets.items():
            with self.subTest(stage_key=stage_key):
                _, reports = self.build_report_chain(stage_key)
                query_count, report = self.count_queries(lambda: db.get_report(self.conn, int(reports[stage_key]["id"])))
                self.assertIsNotNone(report)
                self.assertLessEqual(query_count, budget)

    def test_create_report_query_budget(self) -> None:
        company, _ = self.build_report_chain("financial_underwriting")
        query_count, report = self.count_queries(
            lambda: db.create_report(
                self.conn,
                {"company_id": company["id"], "stage_id": self.stage_id("financial_underwriting")},
            )
        )
        self.assertIsNotNone(report)
        self.assertLessEqual(query_count, 24)

    def test_title_only_update_report_query_budget(self) -> None:
        _, reports = self.build_report_chain("financial_underwriting")
        report = reports["financial_underwriting"]
        query_count, updated = self.count_queries(
            lambda: self.update_report(
                int(report["id"]),
                {"title": "Retitled financial underwriting report"},
                expected_revision=int(report["revision"]),
            )
        )
        self.assertEqual(updated["title"], "Retitled financial underwriting report")
        self.assertLessEqual(query_count, 40)

    def test_get_report_normalizes_values_stored_in_legacy_bucket(self) -> None:
        company = db.create_company(self.conn, {"ticker": "LEG", "name": "Legacy Bucket Corp"})
        report = db.create_report(
            self.conn,
            {"company_id": company["id"], "stage_id": self.stage_id("screening")},
        )
        review_date = db.get_section_field(report["template"]["schema"], "Final Decision", "Review date, if Watchlist")
        self.assertIsNotNone(review_date)

        self.conn.execute(
            "UPDATE reports SET responses_json = ?, metrics_json = ? WHERE id = ?",
            (db.dump_json({}), db.dump_json({review_date["id"]: "2026-06-01"}), report["id"]),
        )
        self.conn.commit()

        normalized = db.get_report(self.conn, report["id"])
        self.assertEqual(normalized["responses"][review_date["id"]], "2026-06-01")
        self.assertNotIn(review_date["id"], normalized["metrics"])

    def test_latest_company_summary_uses_completed_report_and_derives_fields(self) -> None:
        company = db.create_company(self.conn, {"ticker": "SUM", "name": "Summary Corp"})
        report = db.create_report(self.conn, {"company_id": company["id"], "stage_id": self.stage_id("screening")})
        template = report["template"]
        fields = {
            (field["section_title"], field["label"]): field["id"]
            for field in template["schema"]["fields"]
        }
        db.update_report(
            self.conn,
            report["id"],
            {
                "result": db.RESULT_WATCHLIST,
                "responses": {
                    fields[("Final Decision", "Decision")]: "Watchlist",
                    fields[("Final Decision", "Primary reason")]: "Good business but price is not ready.",
                    fields[("One-Page Screening Conclusion", "Next action")]: "Re-screen at target price.",
                    fields[("Final Decision", "Review date, if Watchlist")]: "2026-05-16",
                    fields[("If It Goes To Watchlist", "Price")]: "Below $35",
                },
            },
        )
        draft = db.create_report(self.conn, {"company_id": company["id"], "stage_id": self.stage_id("screening")})
        db.update_report(
            self.conn,
            draft["id"],
            {"summary": "This draft should not appear."},
        )

        companies = db.list_companies(self.conn, bucket="watchlist")
        summary_company = next(item for item in companies if item["ticker"] == "SUM")
        self.assertIn("Good business but price is not ready.", summary_company["latest_summary"])
        self.assertIn("Below $35", summary_company["watchlist_conditions"])
        self.assertEqual(summary_company["next_action"], "Re-screen at target price.")
        self.assertEqual(summary_company["review_date"], "2026-05-16")

    def test_monitoring_tab_excludes_watchlist_rules(self) -> None:
        watch = db.create_company(self.conn, {"ticker": "WAT", "name": "Watch Rule Corp"})
        monitoring = db.create_company(self.conn, {"ticker": "MON", "name": "Monitoring Rule Corp"})
        db.update_company(self.conn, watch["id"], {"bucket": "watchlist"})
        db.update_company(self.conn, monitoring["id"], {"bucket": "monitoring"})
        db.save_monitoring_rule(
            self.conn,
            {
                "company_id": watch["id"],
                "metric_name": "Stock price",
                "comparator": "<=",
                "threshold_value": 35,
                "current_value": 36,
            },
        )
        db.save_monitoring_rule(
            self.conn,
            {
                "company_id": monitoring["id"],
                "metric_name": "Stock price",
                "comparator": "<=",
                "threshold_value": 50,
                "current_value": 49,
            },
        )

        visible_rules = db.list_monitoring_rules(self.conn, bucket="monitoring")
        watchlist = db.list_companies(self.conn, bucket="watchlist")

        self.assertEqual([rule["ticker"] for rule in visible_rules], ["MON"])
        watch_company = next(item for item in watchlist if item["ticker"] == "WAT")
        self.assertEqual(watch_company["monitoring_rules"][0]["metric_name"], "Stock price")

    def test_list_companies_supports_pagination_and_ordering(self) -> None:
        companies = [
            db.create_company(self.conn, {"ticker": "ZZZ", "name": "Zulu Holdings"}),
            db.create_company(self.conn, {"ticker": "AAA", "name": "Alpha Holdings"}),
            db.create_company(self.conn, {"ticker": "MMM", "name": "Mid Holdings"}),
        ]
        db.update_company(self.conn, companies[0]["id"], {"bucket": "watchlist"})

        first_page = db.list_companies(self.conn, order="ticker_asc", page=1, per_page=2)
        second_page = db.list_companies(self.conn, order="ticker_asc", page=2, per_page=2)
        filtered = db.list_companies(self.conn, bucket="watchlist", order="ticker_asc", page=1, per_page=10)

        self.assertEqual([item["ticker"] for item in first_page], ["AAA", "MMM"])
        self.assertEqual([item["ticker"] for item in second_page], ["ZZZ"])
        self.assertEqual([item["ticker"] for item in filtered], ["ZZZ"])
        self.assertEqual(db.count_companies(self.conn), 3)
        self.assertEqual(db.count_companies(self.conn, bucket="watchlist"), 1)


if __name__ == "__main__":
    unittest.main()
