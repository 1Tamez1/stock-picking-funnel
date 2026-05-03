from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an owner bearer token against protected hosted endpoints.")
    parser.add_argument("--base-url", default=os.environ.get("FUNNEL_V2_HOSTED_BASE_URL", "").strip())
    parser.add_argument("--host-header", default=os.environ.get("FUNNEL_V2_HOSTED_HOST_HEADER", "").strip())
    parser.add_argument("--api-token", default=os.environ.get("FUNNEL_V2_API_TOKEN", "").strip())
    parser.add_argument("--report-id", type=int, default=0)
    return parser.parse_args()


def ensure_ok(response: httpx.Response, route: str) -> None:
    if response.status_code >= 400:
        raise SystemExit(
            json.dumps(
                {
                    "route": route,
                    "status_code": response.status_code,
                    "body": response.text,
                },
                indent=2,
            )
        )


def main() -> None:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    from app.config import load_settings

    args = parse_args()
    settings = load_settings()
    base_url = args.base_url or settings.web_origin or "http://127.0.0.1:3000"
    api_token = args.api_token or os.environ.get("FUNNEL_API_TOKEN", "").strip()
    if not api_token:
        raise SystemExit("Provide --api-token or set FUNNEL_V2_API_TOKEN / FUNNEL_API_TOKEN.")

    base_headers = {"Host": args.host_header} if args.host_header else {}
    auth_headers = {
        **base_headers,
        "Authorization": f"Bearer {api_token}",
    }
    results: list[dict[str, object]] = []
    with httpx.Client(base_url=base_url.rstrip("/"), follow_redirects=False, timeout=30.0) as client:
        for route in ("/api/health/runtime", "/api/bootstrap", "/api/reports?include_drafts=true&per_page=5"):
            response = client.get(route, headers=auth_headers)
            ensure_ok(response, route)
            results.append({"route": route, "status_code": response.status_code})

        report_id = int(args.report_id or 0)
        if report_id <= 0:
            reports = client.get("/api/reports?include_drafts=true&per_page=5", headers=auth_headers)
            ensure_ok(reports, "/api/reports?include_drafts=true&per_page=5")
            rows = (reports.json() or {}).get("reports") or []
            if not rows:
                raise SystemExit("No reports available to verify token access.")
            report_id = int(rows[0]["id"])

        route = f"/api/reports/{report_id}"
        report_response = client.get(route, headers=auth_headers)
        ensure_ok(report_response, route)
        results.append(
            {
                "route": route,
                "status_code": report_response.status_code,
                "report_id": report_id,
            }
        )
    print(json.dumps({"base_url": base_url, "report_id": report_id, "results": results}, indent=2))


if __name__ == "__main__":
    main()
