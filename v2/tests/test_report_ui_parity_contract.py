from pathlib import Path
import unittest


ROOT = Path("/Users/Diego/Everything/Projectos_Personales/Value_Investing/stock-picking-funnel-web-app")
REPORT_CLIENT = ROOT / "v2" / "web" / "components" / "native-report-client.tsx"
GLOBALS = ROOT / "v2" / "web" / "app" / "globals.css"


class ReportUiParityContractTest(unittest.TestCase):
    def test_report_page_keeps_v1_critical_surfaces(self) -> None:
        source = REPORT_CLIENT.read_text()
        for marker in [
            "Owner Debug Surfaces",
            "Completion Quality",
            "Source Library",
            "Decision Summary",
            "Report Documents",
            "Agent and Workflow Surface",
            "Advanced JSON Controls",
            "Route Audit",
        ]:
            self.assertIn(marker, source)

    def test_report_page_keeps_v1_interaction_controls(self) -> None:
        source = REPORT_CLIENT.read_text()
        for marker in [
            "Section Sources",
            "Apply to all answers",
            "Delete Source",
            "floating-box",
            "fieldPopover",
            "result-spectrum",
        ]:
            self.assertIn(marker, source)

    def test_report_css_keeps_v1_report_interaction_classes(self) -> None:
        styles = GLOBALS.read_text()
        for marker in [
            ".floating-box",
            ".section-notes",
            ".question-line",
            ".source-picker",
            ".result-spectrum",
            ".report-section-toggle.panel",
        ]:
            self.assertIn(marker, styles)


if __name__ == "__main__":
    unittest.main()
