from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
SOURCE_DB = WORKSPACE / "var" / "funnel.db"
SOURCE_UPLOADS = WORKSPACE / "var" / "uploads"
RUNTIME_ROOT = ROOT / ".tmp" / "playwright-runtime"
RUNTIME_DB = RUNTIME_ROOT / "funnel.e2e.db"
RUNTIME_UPLOADS = RUNTIME_ROOT / "uploads"
MANIFEST_PATH = RUNTIME_ROOT / "manifest.json"
ENV_PATH = RUNTIME_ROOT / "playwright.env"


def rebuild_runtime() -> dict[str, str]:
    shutil.rmtree(RUNTIME_ROOT, ignore_errors=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_DB, RUNTIME_DB)
    shutil.copytree(SOURCE_UPLOADS, RUNTIME_UPLOADS)

    manifest = {
        "runtime_root": str(RUNTIME_ROOT),
        "sqlite_path": str(RUNTIME_DB),
        "upload_root": str(RUNTIME_UPLOADS),
        "source_db": str(SOURCE_DB),
        "source_uploads": str(SOURCE_UPLOADS),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ENV_PATH.write_text(
        "\n".join(
            [
                f'FUNNEL_V2_SQLITE_PATH="{RUNTIME_DB}"',
                f'FUNNEL_V2_UPLOAD_DIR="{RUNTIME_UPLOADS}"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    print(json.dumps(rebuild_runtime(), indent=2))


if __name__ == "__main__":
    main()
