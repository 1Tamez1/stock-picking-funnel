from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = APP_ROOT / "config" / "default_stages.json"
DEFAULT_DB_PATH = APP_ROOT / "var" / "funnel.db"
DEFAULT_UPLOAD_DIR = APP_ROOT / "var" / "uploads"
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def app_root() -> Path:
    return APP_ROOT


def db_path() -> Path:
    return Path(os.environ.get("FUNNEL_DB_PATH", DEFAULT_DB_PATH)).expanduser().resolve()


def upload_dir() -> Path:
    return Path(os.environ.get("FUNNEL_UPLOAD_DIR", DEFAULT_UPLOAD_DIR)).expanduser().resolve()


def max_upload_bytes() -> int:
    raw = os.environ.get("FUNNEL_MAX_UPLOAD_BYTES")
    if raw in (None, ""):
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("FUNNEL_MAX_UPLOAD_BYTES must be an integer.") from exc
    if value < 0:
        raise ValueError("FUNNEL_MAX_UPLOAD_BYTES must be non-negative.")
    return value


def seed_config_path() -> Path:
    return Path(os.environ.get("FUNNEL_SEED_CONFIG", DEFAULT_CONFIG_PATH)).expanduser().resolve()


def load_seed_config() -> dict[str, Any]:
    path = seed_config_path()
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_app_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (APP_ROOT / path).resolve()
