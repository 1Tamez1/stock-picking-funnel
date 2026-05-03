from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"

for candidate in (str(API_ROOT), str(ROOT.parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.auth import AuthService
from app.config import load_settings
from app.shadow import ShadowBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Issue, list, or revoke owner bearer tokens for hosted agent access.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue = subparsers.add_parser("issue", help="Issue a new owner API token.")
    issue.add_argument("--label", default="Agent Token")
    issue.add_argument("--expires-in-days", type=int, default=0)
    issue.add_argument(
        "--scopes",
        default="admin",
        help="Comma-separated token scopes. Valid: read, write_sources, write_reports, finalize_reports, admin.",
    )

    subparsers.add_parser("list", help="List issued owner API tokens.")

    revoke = subparsers.add_parser("revoke", help="Revoke an existing owner API token.")
    revoke.add_argument("--token-id", type=int)
    revoke.add_argument("--token-prefix", default="")

    return parser


def main() -> None:
    args = build_parser().parse_args()

    settings = load_settings()
    shadow = ShadowBackend(settings)
    try:
        service = AuthService(shadow)
        if args.command == "issue":
            payload = service.issue_api_token(
                label=str(args.label or "Agent Token"),
                expires_in_days=int(args.expires_in_days) if int(args.expires_in_days or 0) > 0 else None,
                scopes=str(args.scopes or "admin"),
            )
        elif args.command == "list":
            payload = service.list_api_tokens()
        else:
            payload = service.revoke_api_token(token_id=args.token_id, token_prefix=str(args.token_prefix or ""))
    finally:
        shadow.close()

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
