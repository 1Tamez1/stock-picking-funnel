from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def v1_root() -> Path:
    return workspace_root().parent


def default_sqlite_path() -> Path:
    return v1_root() / "var" / "funnel.db"


def default_upload_dir() -> Path:
    return v1_root() / "var" / "uploads"


def default_contract_dir() -> Path:
    return workspace_root() / "contracts"


def default_shadow_database_url() -> str:
    return f"sqlite+pysqlite:///{(default_contract_dir() / 'shadow' / 'shadow.db').as_posix()}"


def default_endpoint_policies() -> dict[str, str]:
    promoted_reads = {
        "bootstrap": "postgres_primary_with_legacy_fallback",
        "stages": "postgres_primary_with_legacy_fallback",
        "companies.list": "postgres_primary_with_legacy_fallback",
        "companies.detail": "postgres_primary_with_legacy_fallback",
        "templates.list": "postgres_primary_with_legacy_fallback",
        "templates.detail": "postgres_primary_with_legacy_fallback",
        "reports.list": "postgres_primary_with_legacy_fallback",
        "reports.detail": "postgres_primary_with_legacy_fallback",
        "monitoring.list": "postgres_primary_with_legacy_fallback",
    }
    promoted_low_risk_writes = {
        "companies.create": "postgres_primary_with_legacy_fallback",
        "companies.update": "postgres_primary_with_legacy_fallback",
        "templates.create": "postgres_primary_with_legacy_fallback",
        "templates.update": "postgres_primary_with_legacy_fallback",
        "templates.delete": "postgres_primary_with_legacy_fallback",
        "monitoring.create": "postgres_primary_with_legacy_fallback",
        "monitoring.update": "postgres_primary_with_legacy_fallback",
        "reports.create": "postgres_primary_with_legacy_fallback",
        "reports.preview": "postgres_primary_with_legacy_fallback",
        "reports.update": "postgres_primary_with_legacy_fallback",
        "reports.delete": "postgres_primary_with_legacy_fallback",
        "documents.upload": "postgres_primary_with_legacy_fallback",
        "documents.status": "postgres_primary_with_legacy_fallback",
        "documents.download": "postgres_primary_with_legacy_fallback",
        "documents.normalized": "postgres_primary_with_legacy_fallback",
        "report_sources.create": "postgres_primary_with_legacy_fallback",
        "report_sources.update": "postgres_primary_with_legacy_fallback",
        "report_sources.delete": "postgres_primary_with_legacy_fallback",
    }
    return {
        "health": "legacy_only",
        **promoted_reads,
        **promoted_low_risk_writes,
    }


def load_endpoint_policies() -> dict[str, str]:
    policies = default_endpoint_policies()
    raw = os.environ.get("FUNNEL_V2_ENDPOINT_POLICIES", "").strip()
    if not raw:
        return policies
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("FUNNEL_V2_ENDPOINT_POLICIES must be a JSON object.")
    for key, value in loaded.items():
        policies[str(key)] = str(value)
    return policies


@dataclass(slots=True)
class Settings:
    instance_id: str
    sqlite_path: Path
    upload_root: Path
    max_upload_bytes: int
    contract_dir: Path
    postgres_url: str
    backend_mode: str
    endpoint_policies: dict[str, str]
    api_host: str
    api_port: int
    web_origin: str
    storage_mode: str
    session_cookie_name: str
    session_ttl_seconds: int
    session_secure: bool
    owner_seed_email: str
    owner_seed_password: str
    owner_seed_name: str
    web_require_auth: bool
    storage_bucket: str
    storage_region: str
    storage_endpoint_url: str
    storage_access_key_id: str
    storage_secret_access_key: str
    storage_prefix: str
    storage_cache_root: Path
    hosted_runtime_dir: Path
    write_freeze_marker_path: Path
    cutover_state_path: Path


def load_settings() -> Settings:
    max_upload_bytes = int(os.environ.get("FUNNEL_V2_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    contract_dir = Path(os.environ.get("FUNNEL_V2_CONTRACT_DIR", default_contract_dir())).expanduser().resolve()
    storage_cache_root = Path(
        os.environ.get(
            "FUNNEL_V2_STORAGE_CACHE_ROOT",
            str(contract_dir / "storage-cache"),
        )
    ).expanduser().resolve()
    hosted_runtime_dir = Path(
        os.environ.get(
            "FUNNEL_V2_HOSTED_RUNTIME_DIR",
            str(contract_dir / "hosted-runtime"),
        )
    ).expanduser().resolve()
    return Settings(
        instance_id=os.environ.get("FUNNEL_V2_INSTANCE_ID", ""),
        sqlite_path=Path(os.environ.get("FUNNEL_V2_SQLITE_PATH", default_sqlite_path())).expanduser().resolve(),
        upload_root=Path(os.environ.get("FUNNEL_V2_UPLOAD_DIR", default_upload_dir())).expanduser().resolve(),
        max_upload_bytes=max_upload_bytes,
        contract_dir=contract_dir,
        postgres_url=os.environ.get(
            "FUNNEL_V2_POSTGRES_URL",
            os.environ.get("FUNNEL_V2_SHADOW_DATABASE_URL", default_shadow_database_url()),
        ),
        backend_mode=os.environ.get("FUNNEL_V2_BACKEND_MODE", "legacy").strip().lower() or "legacy",
        endpoint_policies=load_endpoint_policies(),
        api_host=os.environ.get("FUNNEL_V2_API_HOST", "127.0.0.1"),
        api_port=int(os.environ.get("FUNNEL_V2_API_PORT", "8211")),
        web_origin=os.environ.get("FUNNEL_V2_WEB_ORIGIN", "http://127.0.0.1:3000"),
        storage_mode=os.environ.get("FUNNEL_V2_STORAGE_MODE", "legacy_local"),
        session_cookie_name=os.environ.get("FUNNEL_V2_SESSION_COOKIE_NAME", "funnel_v2_session"),
        session_ttl_seconds=int(os.environ.get("FUNNEL_V2_SESSION_TTL_SECONDS", str(60 * 60 * 24 * 30))),
        session_secure=os.environ.get("FUNNEL_V2_SESSION_SECURE", "0").strip() in {"1", "true", "yes", "on"},
        owner_seed_email=os.environ.get("FUNNEL_V2_OWNER_EMAIL", "").strip(),
        owner_seed_password=os.environ.get("FUNNEL_V2_OWNER_PASSWORD", ""),
        owner_seed_name=os.environ.get("FUNNEL_V2_OWNER_NAME", "Owner").strip() or "Owner",
        web_require_auth=os.environ.get("FUNNEL_V2_WEB_REQUIRE_AUTH", "0").strip() in {"1", "true", "yes", "on"},
        storage_bucket=os.environ.get("FUNNEL_V2_STORAGE_BUCKET", "").strip(),
        storage_region=os.environ.get("FUNNEL_V2_STORAGE_REGION", "").strip(),
        storage_endpoint_url=os.environ.get("FUNNEL_V2_STORAGE_ENDPOINT_URL", "").strip(),
        storage_access_key_id=os.environ.get("FUNNEL_V2_STORAGE_ACCESS_KEY_ID", "").strip(),
        storage_secret_access_key=os.environ.get("FUNNEL_V2_STORAGE_SECRET_ACCESS_KEY", "").strip(),
        storage_prefix=os.environ.get("FUNNEL_V2_STORAGE_PREFIX", "stock-picking-funnel-v2").strip() or "stock-picking-funnel-v2",
        storage_cache_root=storage_cache_root,
        hosted_runtime_dir=hosted_runtime_dir,
        write_freeze_marker_path=Path(
            os.environ.get(
                "FUNNEL_V2_WRITE_FREEZE_MARKER",
                str(hosted_runtime_dir / "write-freeze.json"),
            )
        )
        .expanduser()
        .resolve(),
        cutover_state_path=Path(
            os.environ.get(
                "FUNNEL_V2_CUTOVER_STATE_PATH",
                str(hosted_runtime_dir / "cutover-state.json"),
            )
        )
        .expanduser()
        .resolve(),
    )
