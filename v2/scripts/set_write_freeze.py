from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enable, disable, or inspect the hosted write-freeze marker.")
    parser.add_argument("command", choices=("enable", "disable", "status"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--message", default="")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--manifest-path", default="")
    return parser


def main() -> None:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    from app.config import load_settings
    from app.runtime_state import read_write_freeze_state
    from app.runtime_state import set_write_freeze

    args = build_parser().parse_args()
    settings = load_settings()
    if args.command == "status":
        payload = read_write_freeze_state(settings)
    elif args.command == "enable":
        payload = set_write_freeze(
            settings,
            enabled=True,
            reason=str(args.reason or ""),
            message=str(args.message or ""),
            source=str(args.source or "manual"),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    else:
        payload = set_write_freeze(settings, enabled=False)

    if args.manifest_path:
        manifest_path = Path(args.manifest_path).expanduser().resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
