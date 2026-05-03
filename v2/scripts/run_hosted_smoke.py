from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"

for candidate in (str(API_ROOT), str(ROOT.parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run smoke checks against a live hosted V2 stack.")
    parser.add_argument("--base-url", default=os.environ.get("FUNNEL_V2_HOSTED_BASE_URL", "").strip())
    parser.add_argument("--host-header", default=os.environ.get("FUNNEL_V2_HOSTED_HOST_HEADER", "").strip())
    parser.add_argument("--email", default=os.environ.get("FUNNEL_V2_OWNER_EMAIL", "").strip())
    parser.add_argument("--password", default=os.environ.get("FUNNEL_V2_OWNER_PASSWORD", ""))
    parser.add_argument("--api-token", default=os.environ.get("FUNNEL_V2_API_TOKEN", "").strip())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    base_url = args.base_url or settings.web_origin or "http://127.0.0.1:3000"
    api_base = base_url.rstrip("/")
    results: list[dict[str, object]] = []
    base_headers = {"Host": args.host_header} if args.host_header else {}
    with httpx.Client(base_url=api_base, follow_redirects=False, timeout=20.0) as client:
        health = client.get("/api/health", headers=base_headers)
        results.append({"route": "/api/health", "status_code": health.status_code})
        headers: dict[str, str] = dict(base_headers)
        if args.api_token:
            headers["Authorization"] = f"Bearer {args.api_token}"
        elif args.email and args.password:
            login = client.post("/api/session/login", json={"email": args.email, "password": args.password}, headers=base_headers)
            results.append({"route": "/api/session/login", "status_code": login.status_code})
            if login.status_code != 201:
                raise SystemExit(json.dumps({"base_url": base_url, "results": results}, indent=2))
        protected_routes = [
            "/api/bootstrap",
            "/api/companies",
            "/api/reports",
            "/api/templates",
            "/api/monitoring",
        ]
        for route in protected_routes:
            response = client.get(route, headers=headers)
            results.append({"route": route, "status_code": response.status_code})
    print(json.dumps({"base_url": base_url, "results": results}, indent=2))


if __name__ == "__main__":
    main()
