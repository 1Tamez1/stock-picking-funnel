from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


class PlaywrightScaffoldingTest(unittest.TestCase):
    def test_playwright_files_exist_for_native_route_and_workflow_coverage(self) -> None:
        expected = [
            WEB_ROOT / "playwright.config.ts",
            WEB_ROOT / "tests" / "e2e" / "fixture-routes.ts",
            WEB_ROOT / "tests" / "e2e" / "helpers.ts",
            WEB_ROOT / "tests" / "e2e" / "live-hosted-stack.spec.ts",
            WEB_ROOT / "tests" / "e2e" / "native-routes.spec.ts",
            WEB_ROOT / "tests" / "e2e" / "report-company-workflow.spec.ts",
            WEB_ROOT / "tests" / "e2e" / "report-stage-parity.spec.ts",
            ROOT / "scripts" / "prepare_playwright_runtime.py",
            ROOT / "scripts" / "run_api_playwright.sh",
            ROOT / "scripts" / "run_web_playwright.sh",
        ]
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing Playwright scaffold: {path}")

    def test_playwright_config_uses_isolated_runtime_scripts(self) -> None:
        config = (WEB_ROOT / "playwright.config.ts").read_text(encoding="utf-8")
        self.assertIn("run_api_playwright.sh", config)
        self.assertIn("run_web_playwright.sh", config)
        self.assertIn("8212", config)


if __name__ == "__main__":
    unittest.main()
