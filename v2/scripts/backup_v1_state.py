from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_manifest() -> dict[str, object]:
    targets = [
        V1_ROOT / "var" / "funnel.db",
        V1_ROOT / "var" / "uploads",
        V1_ROOT / "var" / "report_structure_backups",
        V1_ROOT / "AGENT_RUNBOOK.md",
        V1_ROOT / "AGENT_ISSUES.md",
        V1_ROOT / "agent_payload_templates",
    ]
    files: list[dict[str, object]] = []
    for target in targets:
        if target.is_dir():
            for path in sorted(p for p in target.rglob("*") if p.is_file()):
                files.append(
                    {
                        "path": str(path.relative_to(V1_ROOT)),
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
            continue
        if target.exists():
            files.append(
                {
                    "path": str(target.relative_to(V1_ROOT)),
                    "size_bytes": target.stat().st_size,
                    "sha256": sha256_file(target),
                }
            )
    return {
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "root": str(V1_ROOT),
        "file_count": len(files),
        "files": files,
    }


def main() -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "contracts" / "backups" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = snapshot_manifest()
    (out_dir / "backup-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    db_source = V1_ROOT / "var" / "funnel.db"
    if db_source.exists():
        shutil.copy2(db_source, out_dir / "funnel.db")


if __name__ == "__main__":
    main()
