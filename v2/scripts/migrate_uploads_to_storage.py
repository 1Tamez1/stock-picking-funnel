from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
V1_ROOT = ROOT.parent

for candidate in (str(API_ROOT), str(V1_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.config import load_settings
from app.shadow import file_sha256
from app.shadow import upload_tree_manifest
from app.storage import StorageAdapter
from app.storage import storage_key_from_path
from funnel_app import db as legacy_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror the copied uploads tree into the configured hosted storage backend.")
    parser.add_argument("--manifest-path", default=str(ROOT / "contracts" / "storage-migration-manifest.json"))
    parser.add_argument("--manifest-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    storage = StorageAdapter(settings)
    manifest_path = Path(args.manifest_path).expanduser().resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    file_inventory = upload_tree_manifest(settings.upload_root)
    conn = legacy_db.connect(settings.sqlite_path)
    try:
        document_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM documents ORDER BY id").fetchall()]
        linked_paths: set[str] = set()
        documents: list[dict[str, object]] = []
        for document_id in document_ids:
            document = legacy_db.get_document(conn, document_id)
            if not document:
                continue
            storage_key = str(
                document.get("storage_key")
                or storage_key_from_path(settings.upload_root, document.get("storage_path"), str(document.get("stored_name") or ""))
            )
            normalized_key = str(
                document.get("normalized_storage_key")
                or storage_key_from_path(
                    settings.upload_root,
                    document.get("normalized_text_path"),
                    Path(str(document.get("normalized_text_path") or "")).name,
                )
            )
            if not args.manifest_only:
                storage.mirror_document_record(document)
            storage_path = Path(str(document.get("storage_path") or ""))
            normalized_path = Path(str(document.get("normalized_text_path") or "")) if document.get("normalized_text_path") else None
            if storage_path.exists():
                linked_paths.add(str(storage_path.resolve()))
            if normalized_path and normalized_path.exists():
                linked_paths.add(str(normalized_path.resolve()))
            documents.append(
                {
                    "document_id": int(document["id"]),
                    "storage_key": storage_key,
                    "normalized_storage_key": normalized_key,
                    "storage_sha256": file_sha256(storage_path) if storage_path.exists() else "",
                    "normalized_sha256": file_sha256(normalized_path) if normalized_path and normalized_path.exists() else "",
                }
            )
    finally:
        conn.close()

    orphaned_files: list[dict[str, object]] = []
    for item in file_inventory:
        relative_path = str(item["path"])
        absolute_path = (settings.upload_root / relative_path).resolve()
        if str(absolute_path) not in linked_paths and not args.manifest_only and storage.mode == "s3_compatible":
            storage.mirror_relative_path(relative_path)
        orphaned_files.append(
            {
                "path": relative_path,
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
                "linked_to_document": str(absolute_path) in linked_paths,
            }
        )

    payload = {
        "upload_root": str(settings.upload_root),
        "storage_mode": storage.mode,
        "storage_bucket": settings.storage_bucket,
        "manifest_only": bool(args.manifest_only),
        "file_count": len(file_inventory),
        "document_count": len(documents),
        "documents": documents,
        "files": orphaned_files,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(manifest_path))


if __name__ == "__main__":
    main()
