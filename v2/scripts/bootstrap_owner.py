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


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the single hosted owner account for V2.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Owner")
    args = parser.parse_args()

    settings = load_settings()
    shadow = ShadowBackend(settings)
    try:
        service = AuthService(shadow)
        payload = service.bootstrap_owner(email=args.email, password=args.password, display_name=args.name)
    finally:
        shadow.close()
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
