from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings


def default_hosted_runtime_dir(settings: Settings) -> Path:
    return settings.contract_dir / "hosted-runtime"


def write_freeze_marker_path(settings: Settings) -> Path:
    return settings.write_freeze_marker_path


def cutover_state_path(settings: Settings) -> Path:
    return settings.cutover_state_path


def read_write_freeze_state(settings: Settings) -> dict[str, Any]:
    marker_path = write_freeze_marker_path(settings)
    default_payload: dict[str, Any] = {
        "write_frozen": False,
        "reason": "",
        "message": "",
        "source": "",
        "created_at": "",
    }
    if not marker_path.exists():
        return default_payload
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            **default_payload,
            "write_frozen": True,
            "reason": "invalid_marker",
            "message": "Writes are temporarily frozen while hosted maintenance state is being reconciled.",
            "source": str(marker_path),
        }
    return {
        **default_payload,
        **payload,
        "write_frozen": bool(payload.get("write_frozen", True)),
    }


def write_frozen(settings: Settings) -> bool:
    return bool(read_write_freeze_state(settings).get("write_frozen"))


def read_cutover_state(settings: Settings) -> dict[str, Any]:
    marker_path = cutover_state_path(settings)
    default_payload: dict[str, Any] = {
        "phase": "idle",
        "status": "idle",
        "rollback_authority": "sqlite",
        "cutback_required": False,
        "reason": "",
        "message": "",
        "source": "",
        "created_at": "",
        "manifest_path": "",
    }
    if not marker_path.exists():
        return default_payload
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            **default_payload,
            "phase": "unknown",
            "status": "invalid_marker",
            "cutback_required": True,
            "reason": "invalid_marker",
            "message": "Cutover state marker is unreadable. Treat the hosted stack as rollback-only until it is reconciled.",
            "source": str(marker_path),
        }
    return {
        **default_payload,
        **payload,
        "cutback_required": bool(payload.get("cutback_required", False)),
    }


def set_write_freeze(
    settings: Settings,
    *,
    enabled: bool,
    reason: str = "",
    message: str = "",
    source: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    marker_path = write_freeze_marker_path(settings)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    if not enabled:
        if marker_path.exists():
            marker_path.unlink()
        return read_write_freeze_state(settings)
    payload = {
        "write_frozen": True,
        "reason": reason,
        "message": message or "Writes are temporarily frozen while hosted maintenance runs.",
        "source": source,
        "created_at": created_at,
    }
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def set_cutover_state(
    settings: Settings,
    *,
    phase: str,
    status: str,
    rollback_authority: str = "sqlite",
    cutback_required: bool = False,
    reason: str = "",
    message: str = "",
    source: str = "",
    created_at: str = "",
    manifest_path: str = "",
) -> dict[str, Any]:
    marker_path = cutover_state_path(settings)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "phase": phase,
        "status": status,
        "rollback_authority": rollback_authority,
        "cutback_required": bool(cutback_required),
        "reason": reason,
        "message": message,
        "source": source,
        "created_at": created_at,
        "manifest_path": manifest_path,
    }
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
