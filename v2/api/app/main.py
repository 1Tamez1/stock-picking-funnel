from __future__ import annotations

from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.auth import AuthService
from app.config import load_settings
from app.legacy_bridge import build_bridge
from app.postgres_services import PostgresCompatibilityStore
from app.runtime_state import read_cutover_state
from app.runtime_state import read_write_freeze_state
from app.routers.compatibility import router as compatibility_router
from app.routers.mcp import router as mcp_router
from app.service import CompatibilityService
from app.shadow import ShadowBackend
from app.storage import StorageAdapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        shadow_backend = getattr(app.state, "shadow_backend", None)
        if shadow_backend is not None:
            shadow_backend.close()


def create_app() -> FastAPI:
    settings = load_settings()
    bridge = build_bridge(settings)
    shadow_backend = ShadowBackend(settings)
    postgres_store = PostgresCompatibilityStore(shadow_backend)
    auth_service = AuthService(shadow_backend)
    auth_service.ensure_seed_owner()
    storage = StorageAdapter(settings)
    app = FastAPI(title="Stock Picking Funnel V2", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.bridge = bridge
    app.state.shadow_backend = shadow_backend
    app.state.postgres_store = postgres_store
    app.state.auth_service = auth_service
    app.state.storage = storage
    app.state.service = CompatibilityService(bridge=bridge, shadow=shadow_backend, postgres=postgres_store)
    app.state.instance_id = bridge.instance_id or uuid.uuid4().hex[:12]

    @app.middleware("http")
    async def auth_middleware(request, call_next):
        auth = request.app.state.auth_service
        session_payload = auth.session_from_request(request)
        request.state.session_payload = session_payload
        request.state.write_freeze_state = read_write_freeze_state(request.app.state.settings)
        request.state.cutover_state = read_cutover_state(request.app.state.settings)
        path = request.url.path
        public_api_paths = {
            "/api/health",
            "/api/session",
            "/api/session/login",
            "/api/session/logout",
        }
        protected_app_path = path.startswith("/api/") or path == "/mcp"
        if protected_app_path and path not in public_api_paths and session_payload.required and not session_payload.authenticated:
            headers = {
                "X-Funnel-Instance-Id": request.app.state.bridge.instance_id,
                "X-Funnel-Request-Id": request.app.state.bridge.request_id(),
            }
            return JSONResponse(
                {
                    "error": "Authentication required.",
                    "code": "authentication_required",
                    "request_id": headers["X-Funnel-Request-Id"],
                },
                status_code=401,
                headers=headers,
            )
        write_freeze_state = request.state.write_freeze_state
        if (
            path.startswith("/api/")
            and request.method.upper() in {"POST", "PATCH", "DELETE"}
            and path not in public_api_paths
            and bool(write_freeze_state.get("write_frozen"))
        ):
            headers = {
                "X-Funnel-Instance-Id": request.app.state.bridge.instance_id,
                "X-Funnel-Request-Id": request.app.state.bridge.request_id(),
                "Retry-After": "60",
            }
            return JSONResponse(
                {
                    "error": str(write_freeze_state.get("message") or "Writes are temporarily frozen while hosted maintenance runs."),
                    "code": "write_frozen",
                    "reason": str(write_freeze_state.get("reason") or ""),
                    "request_id": headers["X-Funnel-Request-Id"],
                },
                status_code=503,
                headers=headers,
            )
        return await call_next(request)

    app.include_router(compatibility_router)
    app.include_router(mcp_router)
    return app


app = create_app()
