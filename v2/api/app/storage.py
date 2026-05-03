from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Response
from fastapi.responses import FileResponse

from app.config import Settings


def storage_key_from_path(upload_root: Path, file_path: str | Path | None, fallback: str) -> str:
    if not file_path:
        return fallback
    candidate = Path(file_path)
    try:
        return str(candidate.resolve().relative_to(upload_root.resolve()))
    except ValueError:
        return fallback


@dataclass(slots=True)
class StorageResolution:
    used_remote: bool
    used_local_fallback: bool
    remote_authoritative: bool
    detail: str = ""


class StorageAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_root = settings.storage_cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)

    @property
    def mode(self) -> str:
        return self.settings.storage_mode

    @property
    def remote_authoritative(self) -> bool:
        return self.mode == "s3_compatible"

    def _s3_client(self):
        if self.mode != "s3_compatible":
            return None
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency in hosted mode only
            raise RuntimeError("boto3 is required for FUNNEL_V2_STORAGE_MODE=s3_compatible.") from exc
        return boto3.client(
            "s3",
            endpoint_url=self.settings.storage_endpoint_url or None,
            region_name=self.settings.storage_region or None,
            aws_access_key_id=self.settings.storage_access_key_id or None,
            aws_secret_access_key=self.settings.storage_secret_access_key or None,
        )

    def _bucket_key(self, key: str) -> str:
        prefix = self.settings.storage_prefix.strip("/")
        return f"{prefix}/{key}" if prefix else key

    def mirror_file(self, key: str, local_path: Path, *, content_type: str = "") -> None:
        if self.mode != "s3_compatible":
            return
        if not self.settings.storage_bucket:
            raise RuntimeError("FUNNEL_V2_STORAGE_BUCKET is required for s3_compatible storage mode.")
        client = self._s3_client()
        assert client is not None
        client.upload_file(
            str(local_path),
            self.settings.storage_bucket,
            self._bucket_key(key),
            ExtraArgs={"ContentType": content_type or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"},
        )

    def mirror_relative_path(self, relative_path: str, *, content_type: str = "") -> None:
        local_path = self.settings.upload_root / relative_path
        if not local_path.exists():
            raise FileNotFoundError(relative_path)
        self.mirror_file(relative_path, local_path, content_type=content_type)

    def _read_remote_bytes(self, key: str) -> bytes:
        client = self._s3_client()
        assert client is not None
        result = client.get_object(Bucket=self.settings.storage_bucket, Key=self._bucket_key(key))
        body = result["Body"].read()
        return body if isinstance(body, bytes) else bytes(body)

    def read_bytes_with_resolution(self, key: str, local_path: Path | None = None) -> tuple[bytes, StorageResolution]:
        if self.remote_authoritative:
            try:
                return self._read_remote_bytes(key), StorageResolution(
                    used_remote=True,
                    used_local_fallback=False,
                    remote_authoritative=True,
                )
            except Exception as exc:
                if local_path is not None and local_path.exists():
                    return local_path.read_bytes(), StorageResolution(
                        used_remote=False,
                        used_local_fallback=True,
                        remote_authoritative=True,
                        detail=str(exc),
                    )
                raise
        if local_path is not None and local_path.exists():
            return local_path.read_bytes(), StorageResolution(
                used_remote=False,
                used_local_fallback=False,
                remote_authoritative=False,
            )
        raise FileNotFoundError(key)

    def read_bytes(self, key: str, local_path: Path | None = None) -> bytes:
        return self.read_bytes_with_resolution(key, local_path=local_path)[0]

    def _remote_object_exists(self, key: str) -> bool:
        client = self._s3_client()
        assert client is not None
        try:
            client.head_object(Bucket=self.settings.storage_bucket, Key=self._bucket_key(key))
            return True
        except Exception:
            return False

    def object_exists(self, key: str, local_path: Path | None = None) -> bool:
        if self.remote_authoritative:
            if self._remote_object_exists(key):
                return True
            return local_path is not None and local_path.exists()
        if local_path is not None and local_path.exists():
            return True
        return False

    def response_for_file(
        self,
        *,
        key: str,
        local_path: Path,
        media_type: str,
        filename: str,
        headers: dict[str, str],
    ) -> tuple[Response, StorageResolution]:
        if local_path.exists() and not self.remote_authoritative:
            return (
                FileResponse(local_path, media_type=media_type, filename=filename, headers=headers),
                StorageResolution(
                    used_remote=False,
                    used_local_fallback=False,
                    remote_authoritative=False,
                ),
            )
        content, resolution = self.read_bytes_with_resolution(key, local_path=local_path)
        merged_headers = {
            **headers,
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
        return Response(content=content, media_type=media_type, headers=merged_headers), resolution

    def mirror_document_record(self, document: dict[str, Any]) -> None:
        storage_key = str(document.get("storage_key") or storage_key_from_path(self.settings.upload_root, document.get("storage_path"), document.get("stored_name", "")))
        storage_path = Path(str(document.get("storage_path") or ""))
        if storage_key and storage_path.exists():
            self.mirror_file(storage_key, storage_path, content_type=str(document.get("mime_type") or ""))
        normalized_key = str(
            document.get("normalized_storage_key")
            or storage_key_from_path(
                self.settings.upload_root,
                document.get("normalized_text_path"),
                Path(str(document.get("normalized_text_path") or "")).name,
            )
        )
        normalized_path = Path(str(document.get("normalized_text_path") or "")) if document.get("normalized_text_path") else None
        if normalized_key and normalized_path and normalized_path.exists():
            self.mirror_file(normalized_key, normalized_path, content_type="text/plain; charset=utf-8")
