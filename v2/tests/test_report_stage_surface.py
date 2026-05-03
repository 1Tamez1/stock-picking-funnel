from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
V1_ROOT = ROOT.parent


class ReportStageSurfaceTest(unittest.TestCase):
    def test_stage_registry_covers_all_live_stage_keys(self) -> None:
        registry = (WEB_ROOT / "components" / "report-stage-registry.tsx").read_text(encoding="utf-8")
        conn = sqlite3.connect(V1_ROOT / "var" / "funnel.db")
        try:
            stage_keys = [row[0] for row in conn.execute("SELECT key FROM stages ORDER BY sequence ASC").fetchall()]
        finally:
            conn.close()
        for stage_key in stage_keys:
            with self.subTest(stage_key=stage_key):
                self.assertIn(f'"{stage_key}"', registry)

    def test_dedicated_stage_component_files_exist(self) -> None:
        expected = [
            WEB_ROOT / "components" / "report-stages" / "data-collection-stage.tsx",
            WEB_ROOT / "components" / "report-stages" / "screening-stage.tsx",
            WEB_ROOT / "components" / "report-stages" / "business-underwriting-stage.tsx",
            WEB_ROOT / "components" / "report-stages" / "management-underwriting-stage.tsx",
            WEB_ROOT / "components" / "report-stages" / "financial-underwriting-stage.tsx",
            WEB_ROOT / "components" / "report-stages" / "valuation-position-size-stage.tsx",
            WEB_ROOT / "components" / "report-stages" / "execution-rules-stage.tsx",
        ]
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing dedicated stage component: {path}")

    def test_registry_imports_dedicated_stage_components(self) -> None:
        registry = (WEB_ROOT / "components" / "report-stage-registry.tsx").read_text(encoding="utf-8")
        required_imports = [
            "DataCollectionStageSurface",
            "ScreeningStageSurface",
            "BusinessUnderwritingStageSurface",
            "ManagementUnderwritingStageSurface",
            "FinancialUnderwritingStageSurface",
            "ValuationPositionSizeStageSurface",
            "ExecutionRulesStageSurface",
        ]
        for item in required_imports:
            with self.subTest(item=item):
                self.assertIn(item, registry)

    def test_native_report_client_uses_stage_renderer_registry(self) -> None:
        component = (WEB_ROOT / "components" / "native-report-client.tsx").read_text(encoding="utf-8")
        self.assertIn("renderReportStageSurface", component)
        self.assertIn("renderTemplateSection", component)
        self.assertIn("omitReadonlyEntries(formState.responses, readonlyFieldIds)", component)
        self.assertIn("omitReadonlyEntries(formState.metrics, readonlyFieldIds)", component)

    def test_source_durability_helper_tracks_all_states(self) -> None:
        helper = (WEB_ROOT / "lib" / "source-durability.ts").read_text(encoding="utf-8")
        for state in ("ready", "limited", "pending", "link_only", "failed"):
            with self.subTest(state=state):
                self.assertIn(f'"{state}"', helper)

    def test_agent_runbook_surface_remains_explicit(self) -> None:
        component = (WEB_ROOT / "components" / "native-report-client.tsx").read_text(encoding="utf-8")
        required = [
            "report.agent_contract.goal",
            "report.agent_contract.guidance",
            "report.workflow.latest_upstream_report",
            "report.suggested_sources",
            "report.company_sources",
            "report.agent_contract.readonly_field_ids",
        ]
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, component)


if __name__ == "__main__":
    unittest.main()
