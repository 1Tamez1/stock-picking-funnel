# V2 Workspace

This directory contains the side-by-side web migration workspace.

## Safety Rules

- V1 at the repository root remains the canonical reference implementation.
- V2 code lives only inside `v2/`.
- All parity, migration, and rollback tooling must be able to read the root V1 app and `var/` data without mutating them.
- The current FastAPI compatibility layer intentionally delegates to the V1 SQLite/domain implementation to avoid silent logic drift while the PostgreSQL-native domain port is still incomplete.

## Layout

- `api/`: FastAPI compatibility/backend service plus PostgreSQL migration skeleton.
- `web/`: Next.js App Router shell with canonical page routes.
- `worker/`: background worker entrypoints.
- `contracts/`: generated parity fixtures, backups, and migration manifests.
- `scripts/`: backup, fixture export, migration, verification, and run tooling.
- `tests/`: V2-specific parity and safety tests.

## Current Implementation

- Compatibility API: V1-compatible `/api/*` routes exposed through FastAPI while reading/writing against the copied V1 SQLite database.
- Target schema: SQLAlchemy models and Alembic migration for the PostgreSQL target shape, including `public_id` and `slug` for routed pages.
- Worker split: separate worker entrypoint preserving V1 background job semantics.
- Routed web shell: Next.js App Router pages for `/dashboard`, `/companies`, `/companies/[companyHandle]`, `/reports`, `/reports/[reportHandle]`, `/funnel`, `/monitoring`, `/watchlist`, `/archive`, and `/templates`.
- Parity artifacts: backup manifest, fixture export, and migration dry-run manifest under `contracts/`.

## Run

From the target workspace root:

```bash
./v2/scripts/run_api.sh
```

For autoreload during local development:

```bash
FUNNEL_V2_API_RELOAD=1 ./v2/scripts/run_api.sh
```

In another shell:

```bash
./v2/scripts/run_worker.sh
```

In another shell:

```bash
cd v2/web
npm run dev
```

The default API base is `http://127.0.0.1:8211` and the default web origin is `http://127.0.0.1:3000`.

## Verify

Run the full implemented verification set:

```bash
./v2/scripts/verify_v2.sh
```

That script executes:

- V1 backup capture into `v2/contracts/backups/`
- parity fixture export into `v2/contracts/fixtures/`
- migration dry-run manifest generation into `v2/contracts/migration-dry-run.json`
- parity artifact shape check
- V2 Python test suite
- production Next.js build

## Status

This workspace is a hosted-ready migration workspace, not a completed final cutover:

- Preserved now: compatibility API surface, canonical routed pages, parity tooling, PostgreSQL promotion/fallback framework, separate worker process, single-owner auth/session support, and hosted deployment scaffolding.
- Hosted operation now supported: owner bootstrap, `/login`, `/api/session/*`, protected runtime health, optional S3-compatible storage mirroring, and request-local legacy fallback on promoted PostgreSQL routes.
- Still not final cutover: SQLite remains the rollback authority, `/__legacy/...` fallbacks remain present, and agent/report/document workflows still preserve legacy semantics under compatibility comparison instead of a fully independent domain rewrite.

## Hosted Operations

Hosted single-owner tooling now lives under `v2/`:

- `scripts/bootstrap_owner.py`: create or reset the owner account.
- `scripts/manage_owner_tokens.py`: issue, list, and revoke bearer tokens for agent/runbook access.
- `scripts/verify_owner_token.py`: verify bearer-token access against protected hosted endpoints.
- `scripts/set_write_freeze.py`: enable, disable, or inspect the hosted write-freeze marker.
- `scripts/migrate_uploads_to_storage.py`: mirror the copied upload tree into the configured storage backend and write a manifest.
- `scripts/run_hosted_smoke.py`: smoke-check the hosted stack with either session login or bearer token auth.
- `scripts/run_hosted_validation.py`: run a deeper hosted flow covering report create/save/block, source CRUD, document upload/poll/download, finalize verification, and promoted-route fallback/artifact enforcement.
- `scripts/rehearse_cutover.sh`: rehearse the hosted single-user cutover with automatic cutback on failure.
- `scripts/cutback_hosted_state.sh`: restore hosted state from a backup if parity gates fail.
- `scripts/verify_restore.sh`: restore a backup and rerun verification/smoke checks.

The immutable hosted stack definition now lives in `deploy/`:

- `deploy/docker-compose.yml`
- `deploy/Dockerfile.api`
- `deploy/Dockerfile.worker`
- `deploy/Dockerfile.web`
- `deploy/.env.local.example`
- `deploy/.env.staging.example`
- `deploy/.env.hosted.example`
- `deploy/.env.validation.example`
- `deploy/up.sh`
- `deploy/down.sh`
- `deploy/reset.sh`
- `deploy/validate.sh`

The live validation artifact root is `contracts/hosted-runtime/`. A full deploy validation run writes a timestamped bundle under `contracts/hosted-runtime/live-stack-validations/` with:

- the captured stack boot manifest
- bearer-token verification output
- session-auth smoke and deep validation output
- bearer-token smoke and deep validation output
- optional live Playwright output
- a failure report if any stage aborts or a promoted route falls back without explicit parity evidence
