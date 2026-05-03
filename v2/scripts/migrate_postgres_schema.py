from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"

for candidate in (str(API_ROOT), str(ROOT.parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.db.base import Base
from app.db.session import build_engine


def main() -> None:
    settings = load_settings()
    engine = build_engine(settings)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    print("PostgreSQL-compatible schema ensured.")


if __name__ == "__main__":
    main()
