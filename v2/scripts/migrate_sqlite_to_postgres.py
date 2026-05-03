from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
V1_ROOT = ROOT.parent

for candidate in (str(V1_ROOT), str(API_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.shadow import ShadowBackend


def main() -> None:
    settings = load_settings()
    settings.backend_mode = "shadow"
    shadow_backend = ShadowBackend(settings)
    result = shadow_backend.sync_from_source(reason="migration-script", force=True)
    if result is None:
        raise SystemExit("Shadow backend is not available.")
    print(f"Wrote shadow import manifest to {result.manifest_path}")
    print(f"Shadow import status: {result.status}")


if __name__ == "__main__":
    main()
