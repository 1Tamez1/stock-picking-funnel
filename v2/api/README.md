# V2 API

The current V2 backend has these responsibilities:

1. Preserve the current V1 behavior through a FastAPI compatibility surface.
2. Promote PostgreSQL-backed reads and selected writes behind request-local fallback.
3. Define the target PostgreSQL/Alembic/SQLAlchemy shape for the eventual final cutover.

Until the domain migration is complete, legacy SQLite remains the rollback authority and any PostgreSQL mismatch falls back to the preserved legacy result.

## Run

```bash
../scripts/run_api.sh
```

Set `FUNNEL_V2_API_RELOAD=1` only when file watching is supported by the host environment.

## Current behavior

- `app.main` boots a FastAPI app backed by `app.legacy_bridge.LegacyBridge`.
- Compatibility routes in `app/routers/compatibility.py` expose the current `/api/*` surface and map V1 exceptions to V1-style responses.
- Owner auth/session routes live under `/api/session/*`; all non-health compatibility routes are protected once an owner account exists.
- `app/db/models.py` and Alembic define the PostgreSQL target schema, including owner/session tables.
- Promoted reads and selected writes can serve from PostgreSQL first with legacy fallback, while higher-risk parity still depends on compatibility comparison.
