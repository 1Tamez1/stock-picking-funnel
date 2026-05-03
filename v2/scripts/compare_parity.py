from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    fixtures = ROOT / "contracts" / "fixtures" / "v1-parity-fixtures.json"
    parity_matrix = ROOT / "contracts" / "parity-matrix.json"
    shadow_root = ROOT / "contracts" / "shadow"
    if not fixtures.exists():
        raise SystemExit("Missing fixtures. Run export_parity_fixtures.py first.")
    if not parity_matrix.exists():
        raise SystemExit("Missing parity matrix. Run build_parity_matrix.py first.")
    payload = json.loads(fixtures.read_text(encoding="utf-8"))
    required = {"schema_inventory", "payloads", "reference_samples"}
    missing = sorted(required - set(payload))
    if missing:
        raise SystemExit(f"Fixture file missing keys: {', '.join(missing)}")
    parity = json.loads(parity_matrix.read_text(encoding="utf-8"))
    parity_required = {
        "expected_v2_routes",
        "legacy_fallback_routes",
        "route_migration_status",
        "legacy_views",
        "stage_renderer_keys",
        "source_durability_states",
        "critical_ui_actions",
        "api_endpoints",
    }
    parity_missing = sorted(parity_required - set(parity))
    if parity_missing:
        raise SystemExit(f"Parity matrix missing keys: {', '.join(parity_missing)}")
    shadow_manifest = shadow_root / "migration-import-manifest.json"
    if not shadow_manifest.exists():
        raise SystemExit("Missing shadow import manifest. Run migrate_sqlite_to_postgres.py first.")
    shadow_payload = json.loads(shadow_manifest.read_text(encoding="utf-8"))
    shadow_required = {"status", "tables", "upload_files", "document_file_checks", "source_fingerprint"}
    shadow_missing = sorted(shadow_required - set(shadow_payload))
    if shadow_missing:
        raise SystemExit(f"Shadow import manifest missing keys: {', '.join(shadow_missing)}")
    for directory in ("read-parity", "write-parity", "worker-parity"):
        artifact_dir = shadow_root / directory
        if not artifact_dir.exists() or not any(artifact_dir.glob("*.json")):
            raise SystemExit(f"Missing shadow artifacts in {artifact_dir}. Run generate_shadow_artifacts.py first.")
    promotion_summary = shadow_root / "promotion-summary.json"
    if not promotion_summary.exists():
        raise SystemExit("Missing promotion summary. Run generate_shadow_artifacts.py first.")
    for directory in ("fallback-events", "contract-mismatches"):
        artifact_dir = shadow_root / directory
        if not artifact_dir.exists():
            raise SystemExit(f"Missing shadow artifact directory {artifact_dir}.")
    print("Parity fixture file present and structurally valid.")


if __name__ == "__main__":
    main()
