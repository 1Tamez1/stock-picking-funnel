from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
CONTRACT_PATH = ROOT / "contracts" / "parity-matrix.json"

EXPECTED_V2_ROUTES = [
    "/dashboard",
    "/pool",
    "/funnel",
    "/reports",
    "/companies",
    "/companies/[companyHandle]",
    "/reports/[reportHandle]",
    "/monitoring",
    "/watchlist",
    "/archive",
    "/templates",
]

LEGACY_FALLBACK_ROUTES = [
    "/__legacy/dashboard",
    "/__legacy/pool",
    "/__legacy/funnel",
    "/__legacy/reports",
    "/__legacy/monitoring",
    "/__legacy/watchlist",
    "/__legacy/archive",
    "/__legacy/templates",
    "/__legacy/companies/[companyHandle]",
    "/__legacy/reports/[reportHandle]",
]

STAGE_RENDERER_KEYS = [
    "data_collection",
    "screening",
    "business_underwriting",
    "management_underwriting",
    "financial_underwriting",
    "valuation_position_size",
    "execution_rules",
]

SOURCE_DURABILITY_STATES = ["ready", "limited", "pending", "link_only", "failed"]

ROUTE_MIGRATION_STATUS = {
    "/dashboard": "native_primary_with_legacy_fallback",
    "/pool": "native_primary_with_legacy_fallback",
    "/funnel": "native_primary_with_legacy_fallback",
    "/reports": "native_primary_with_legacy_fallback",
    "/companies": "native_only",
    "/companies/[companyHandle]": "native_primary_with_legacy_fallback",
    "/reports/[reportHandle]": "native_primary_with_legacy_fallback",
    "/monitoring": "native_primary_with_legacy_fallback",
    "/watchlist": "native_primary_with_legacy_fallback",
    "/archive": "native_primary_with_legacy_fallback",
    "/templates": "native_primary_with_legacy_fallback",
}

CRITICAL_ACTIONS = [
    "renderView",
    "openCompany",
    "openReport",
    "createCompanyFromDialog",
    "createReportForCompany",
    "uploadDocument",
    "saveReport",
    "refreshCompletionPreview",
    "createReportSource",
    "deleteReportSource",
    "deleteReport",
    "renderMonitoring",
    "renderTemplates",
    "updateMonitoringRule",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_nav_views(index_html: str) -> list[str]:
    return sorted(set(re.findall(r'data-view="([^"]+)"', index_html)))


def extract_api_endpoints(*texts: str) -> list[str]:
    pattern = re.compile(r"/api/[A-Za-z0-9{}:_/\-]+")
    return sorted(set(match for text in texts for match in pattern.findall(text)))


def extract_test_names(path: Path) -> list[str]:
    return re.findall(r"def (test_[a-z0-9_]+)\(", read(path))


def extract_runbook_headings(markdown: str) -> list[str]:
    return [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]


def extract_route_files() -> list[str]:
    return sorted(str(path.relative_to(ROOT / "web")) for path in (ROOT / "web" / "app").rglob("page.tsx"))


def main() -> None:
    legacy_index = read(V1_ROOT / "static" / "index.html")
    legacy_app = read(V1_ROOT / "static" / "app.js")
    runbook = read(V1_ROOT / "AGENT_RUNBOOK.md")
    api_tests = extract_test_names(V1_ROOT / "tests" / "test_api.py")
    db_tests = extract_test_names(V1_ROOT / "tests" / "test_db.py")
    payload_manifest = json.loads(read(V1_ROOT / "agent_payload_templates" / "manifest.json"))

    payload_template_files = sorted(path.name for path in (V1_ROOT / "agent_payload_templates").glob("*.json"))
    parity = {
        "expected_v2_routes": EXPECTED_V2_ROUTES,
        "legacy_fallback_routes": LEGACY_FALLBACK_ROUTES,
        "route_migration_status": ROUTE_MIGRATION_STATUS,
        "legacy_views": extract_nav_views(legacy_index),
        "stage_renderer_keys": STAGE_RENDERER_KEYS,
        "source_durability_states": SOURCE_DURABILITY_STATES,
        "critical_ui_actions": {
            name: (f"function {name}" in legacy_app or f"async function {name}" in legacy_app)
            for name in CRITICAL_ACTIONS
        },
        "api_endpoints": extract_api_endpoints(read(V1_ROOT / "funnel_app" / "server.py"), runbook),
        "api_test_cases": api_tests,
        "db_test_cases": db_tests,
        "agent_assets": {
            "runbook": "AGENT_RUNBOOK.md",
            "issues_log": "AGENT_ISSUES.md",
            "payload_templates": payload_template_files,
            "payload_manifest_templates": payload_manifest.get("templates", []),
            "payload_generator": "tools/generate_report_payload_templates.mjs",
        },
        "runbook_headings": extract_runbook_headings(runbook),
        "v2_route_files": extract_route_files(),
    }
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(parity, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
