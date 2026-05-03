from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


class WebParityRoutesTest(unittest.TestCase):
    def test_expected_route_pages_exist(self) -> None:
        expected = [
            WEB_ROOT / "app" / "dashboard" / "page.tsx",
            WEB_ROOT / "app" / "pool" / "page.tsx",
            WEB_ROOT / "app" / "funnel" / "page.tsx",
            WEB_ROOT / "app" / "reports" / "page.tsx",
            WEB_ROOT / "app" / "companies" / "page.tsx",
            WEB_ROOT / "app" / "companies" / "[companyHandle]" / "page.tsx",
            WEB_ROOT / "app" / "reports" / "[reportHandle]" / "page.tsx",
            WEB_ROOT / "app" / "monitoring" / "page.tsx",
            WEB_ROOT / "app" / "watchlist" / "page.tsx",
            WEB_ROOT / "app" / "archive" / "page.tsx",
            WEB_ROOT / "app" / "templates" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "dashboard" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "pool" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "funnel" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "reports" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "monitoring" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "watchlist" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "archive" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "templates" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "companies" / "[companyHandle]" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "reports" / "[reportHandle]" / "page.tsx",
        ]
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing route page: {path}")

    def test_primary_routes_no_longer_use_legacy_frame_host(self) -> None:
        route_files = [
            WEB_ROOT / "app" / "dashboard" / "page.tsx",
            WEB_ROOT / "app" / "pool" / "page.tsx",
            WEB_ROOT / "app" / "funnel" / "page.tsx",
            WEB_ROOT / "app" / "reports" / "page.tsx",
            WEB_ROOT / "app" / "companies" / "page.tsx",
            WEB_ROOT / "app" / "companies" / "[companyHandle]" / "page.tsx",
            WEB_ROOT / "app" / "reports" / "[reportHandle]" / "page.tsx",
            WEB_ROOT / "app" / "monitoring" / "page.tsx",
            WEB_ROOT / "app" / "watchlist" / "page.tsx",
            WEB_ROOT / "app" / "archive" / "page.tsx",
            WEB_ROOT / "app" / "templates" / "page.tsx",
        ]
        for path in route_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("LegacyParityFrame", text)

    def test_primary_routes_with_fallback_use_surface_header(self) -> None:
        route_files = [
            WEB_ROOT / "app" / "dashboard" / "page.tsx",
            WEB_ROOT / "app" / "pool" / "page.tsx",
            WEB_ROOT / "app" / "funnel" / "page.tsx",
            WEB_ROOT / "app" / "reports" / "page.tsx",
            WEB_ROOT / "app" / "companies" / "[companyHandle]" / "page.tsx",
            WEB_ROOT / "app" / "reports" / "[reportHandle]" / "page.tsx",
            WEB_ROOT / "app" / "monitoring" / "page.tsx",
            WEB_ROOT / "app" / "watchlist" / "page.tsx",
            WEB_ROOT / "app" / "archive" / "page.tsx",
            WEB_ROOT / "app" / "templates" / "page.tsx",
        ]
        for path in route_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("SurfaceHeader", text)

    def test_companies_index_is_native_page(self) -> None:
        text = (WEB_ROOT / "app" / "companies" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("PageHeader", text)
        self.assertIn("NativeCompanyCreateForm", text)

    def test_hidden_fallback_routes_use_legacy_frame_host(self) -> None:
        route_files = [
            WEB_ROOT / "app" / "%5F%5Flegacy" / "dashboard" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "pool" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "funnel" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "reports" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "monitoring" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "watchlist" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "archive" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "templates" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "companies" / "[companyHandle]" / "page.tsx",
            WEB_ROOT / "app" / "%5F%5Flegacy" / "reports" / "[reportHandle]" / "page.tsx",
        ]
        for path in route_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("LegacyParityFrame", text)

    def test_next_app_shell_exposes_pool_route(self) -> None:
        shell = (WEB_ROOT / "components" / "app-shell.tsx").read_text(encoding="utf-8")
        self.assertIn('"/pool"', shell)
        self.assertIn('"/templates"', shell)


if __name__ == "__main__":
    unittest.main()
