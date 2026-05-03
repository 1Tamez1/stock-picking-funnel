from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FixtureExportShapeTest(unittest.TestCase):
    def test_fixture_export_contains_core_payload_sections(self) -> None:
        script = (ROOT / "scripts" / "export_parity_fixtures.py").read_text(encoding="utf-8")
        self.assertIn("schema_inventory", script)
        self.assertIn("payloads", script)
        self.assertIn("reference_samples", script)
        self.assertIn("legacy_db.get_report", script)
        self.assertIn("legacy_db.get_company", script)
        self.assertIn("legacy_db.get_document", script)

    def test_parity_matrix_script_tracks_routes_and_agent_assets(self) -> None:
        script = (ROOT / "scripts" / "build_parity_matrix.py").read_text(encoding="utf-8")
        self.assertIn("expected_v2_routes", script)
        self.assertIn("legacy_fallback_routes", script)
        self.assertIn("route_migration_status", script)
        self.assertIn("stage_renderer_keys", script)
        self.assertIn("source_durability_states", script)
        self.assertIn("AGENT_RUNBOOK.md", script)
        self.assertIn("agent_payload_templates", script)
        self.assertIn("critical_ui_actions", script)

    def test_shadow_scripts_and_artifact_checks_exist(self) -> None:
        compare_script = (ROOT / "scripts" / "compare_parity.py").read_text(encoding="utf-8")
        generate_script = (ROOT / "scripts" / "generate_shadow_artifacts.py").read_text(encoding="utf-8")
        verify_postgres_script = (ROOT / "scripts" / "verify_postgres_promotion.py").read_text(encoding="utf-8")
        config = (ROOT / "api" / "app" / "config.py").read_text(encoding="utf-8")
        shadow = (ROOT / "api" / "app" / "shadow.py").read_text(encoding="utf-8")
        self.assertIn("migration-import-manifest.json", compare_script)
        self.assertIn("read-parity", compare_script)
        self.assertIn("write-parity", compare_script)
        self.assertIn("worker-parity", compare_script)
        self.assertIn("promotion-summary.json", compare_script)
        self.assertIn("fallback-events", compare_script)
        self.assertIn("contract-mismatches", compare_script)
        self.assertIn("FUNNEL_V2_BACKEND_MODE", config)
        self.assertIn("FUNNEL_V2_ENDPOINT_POLICIES", config)
        self.assertIn("postgres_primary_with_legacy_fallback", config)
        self.assertIn("shadow", config)
        self.assertIn("postgres_verify", shadow)
        self.assertIn("record_fallback_event", shadow)
        self.assertIn("exercise_common_routes", generate_script)
        self.assertIn("FUNNEL_V2_POSTGRES_URL", verify_postgres_script)
        self.assertIn("X-Funnel-Served-By", verify_postgres_script)


if __name__ == "__main__":
    unittest.main()
