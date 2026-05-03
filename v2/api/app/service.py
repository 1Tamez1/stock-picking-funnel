from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime as real_datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Callable

from fastapi import Request

from app.legacy_bridge import LegacyBridge
from app.postgres_services import PostgresCompatibilityStore
from app import postgres_services
from app import native_authority
from app.shadow import ShadowBackend
from app.shadow import diff_values
from app.shadow import normalize_payload
from app.shadow import strip_transport_fields

from funnel_app import db as legacy_db

POLICY_LEGACY_ONLY = "legacy_only"
POLICY_SHADOW_COMPARE = "shadow_compare"
POLICY_POSTGRES_PRIMARY_WITH_LEGACY_FALLBACK = "postgres_primary_with_legacy_fallback"


@dataclass(slots=True)
class ExecutionResult:
    payload: dict[str, Any]
    served_by: str
    policy: str
    fallback_used: bool
    artifact_path: Path | None
    backend_mode: str

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Funnel-Execution-Mode": self.backend_mode,
            "X-Funnel-Execution-Policy": self.policy,
            "X-Funnel-Served-By": self.served_by,
            "X-Funnel-Legacy-Fallback": "1" if self.fallback_used else "0",
            "X-Funnel-Parity-Artifact": str(self.artifact_path or ""),
        }


@dataclass(slots=True)
class CompatibilityService:
    bridge: LegacyBridge
    shadow: ShadowBackend
    postgres: PostgresCompatibilityStore

    @property
    def backend_mode(self) -> str:
        return self.bridge.settings.backend_mode

    @property
    def shadow_enabled(self) -> bool:
        return self.shadow.enabled

    def request_key(self, request: Request, extra: dict[str, Any] | None = None) -> str:
        query: dict[str, list[str]] = {}
        for key in sorted(set(request.query_params.keys())):
            query[key] = request.query_params.getlist(key)
        payload = {
            "method": request.method,
            "path": request.url.path,
            "query": query,
            "extra": extra or {},
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def policy_for(self, category: str) -> str:
        return self.bridge.settings.endpoint_policies.get(category, POLICY_SHADOW_COMPARE)

    def _normalized_compare_pair(self, legacy_payload: dict[str, Any], postgres_payload: dict[str, Any]) -> tuple[Any, Any]:
        return (
            normalize_payload(strip_transport_fields(legacy_payload)),
            normalize_payload(strip_transport_fields(postgres_payload)),
        )

    @contextmanager
    def deterministic_write_context(self, request_key: str):
        seed = hashlib.sha256(request_key.encode("utf-8")).digest()
        base_seconds = int.from_bytes(seed[:6], "big") % (60 * 60 * 24 * 365)
        base = real_datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=base_seconds)
        uuid_counter = {"value": 0}
        time_counter = {"value": 0}

        class DeterministicDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                current = base + timedelta(seconds=time_counter["value"])
                time_counter["value"] += 1
                if tz is None:
                    return current.replace(tzinfo=None)
                return current.astimezone(tz)

        original_datetime = legacy_db.datetime
        original_uuid4 = legacy_db.uuid.uuid4
        original_postgres_now_utc = postgres_services.now_utc
        original_native_now_utc = native_authority.now_utc
        original_native_datetime = native_authority.datetime

        def deterministic_uuid4():
            uuid_counter["value"] += 1
            payload = hashlib.sha256(f"{request_key}:{uuid_counter['value']}".encode("utf-8")).digest()[:16]
            return uuid.UUID(bytes=payload)

        def deterministic_now_utc():
            current = base + timedelta(seconds=time_counter["value"])
            time_counter["value"] += 1
            return current

        legacy_db.datetime = DeterministicDateTime
        legacy_db.uuid.uuid4 = deterministic_uuid4
        postgres_services.now_utc = deterministic_now_utc
        native_authority.now_utc = deterministic_now_utc
        native_authority.datetime = DeterministicDateTime
        try:
            yield
        finally:
            legacy_db.datetime = original_datetime
            legacy_db.uuid.uuid4 = original_uuid4
            postgres_services.now_utc = original_postgres_now_utc
            native_authority.now_utc = original_native_now_utc
            native_authority.datetime = original_native_datetime

    def load_postgres_read(self, *, category: str, request_key: str) -> dict[str, Any]:
        snapshot = self.shadow.load_snapshot_record(request_key)
        if snapshot is None:
            raise LookupError("snapshot_missing")
        if snapshot.category != category:
            raise LookupError("snapshot_category_mismatch")
        current_fingerprint = self.shadow.source_fingerprint()
        if snapshot.source_fingerprint != current_fingerprint:
            raise LookupError("snapshot_stale")
        return snapshot.payload

    def execute_read(
        self,
        request: Request,
        category: str,
        legacy_loader: Callable[[], dict[str, Any]],
        *,
        extra: dict[str, Any] | None = None,
        postgres_loader: Callable[[str], dict[str, Any]] | None = None,
    ) -> ExecutionResult:
        policy = self.policy_for(category)
        request_key = self.request_key(request, extra)

        if self.backend_mode == "legacy" or policy == POLICY_LEGACY_ONLY:
            return ExecutionResult(
                payload=legacy_loader(),
                served_by="legacy",
                policy=policy,
                fallback_used=False,
                artifact_path=None,
                backend_mode=self.backend_mode,
            )

        if self.backend_mode == "shadow" or policy == POLICY_SHADOW_COMPARE:
            payload = legacy_loader()
            artifact = self.shadow.observe_read(category, request_key, payload) if self.shadow_enabled else None
            artifact_path = Path(str(artifact.get("artifact_path"))) if artifact and artifact.get("artifact_path") else None
            return ExecutionResult(
                payload=payload,
                served_by="legacy",
                policy=policy,
                fallback_used=False,
                artifact_path=artifact_path,
                backend_mode=self.backend_mode,
            )

        loader = postgres_loader or (lambda snapshot_request_key: self.load_postgres_read(category=category, request_key=snapshot_request_key))
        try:
            postgres_payload = loader(request_key)
        except Exception as exc:
            payload = legacy_loader()
            observe_artifact = self.shadow.observe_read(category, request_key, payload) if self.shadow_enabled else None
            linked_artifact = (
                Path(str(observe_artifact.get("artifact_path")))
                if observe_artifact and observe_artifact.get("artifact_path")
                else None
            )
            fallback_path = self.shadow.record_fallback_event(
                category=category,
                request_key=request_key,
                policy=policy,
                reason="postgres_unavailable",
                primary_backend="postgres",
                detail=str(exc),
                artifact_path=linked_artifact,
            )
            return ExecutionResult(
                payload=payload,
                served_by="legacy",
                policy=policy,
                fallback_used=True,
                artifact_path=fallback_path,
                backend_mode=self.backend_mode,
            )

        legacy_payload = legacy_loader()
        normalized_legacy, normalized_postgres = self._normalized_compare_pair(legacy_payload, postgres_payload)
        diffs = diff_values(normalized_legacy, normalized_postgres)
        if diffs:
            mismatch_path = self.shadow.record_contract_mismatch(
                category=category,
                request_key=request_key,
                policy=policy,
                legacy_payload=legacy_payload,
                postgres_payload=postgres_payload,
                diffs=diffs,
            )
            observe_artifact = self.shadow.observe_read(category, request_key, legacy_payload) if self.shadow_enabled else None
            linked_artifact = (
                Path(str(observe_artifact.get("artifact_path")))
                if observe_artifact and observe_artifact.get("artifact_path")
                else mismatch_path
            )
            fallback_path = self.shadow.record_fallback_event(
                category=category,
                request_key=request_key,
                policy=policy,
                reason="contract_mismatch",
                primary_backend="postgres",
                detail=f"{len(diffs)} mismatched paths",
                artifact_path=linked_artifact,
            )
            return ExecutionResult(
                payload=legacy_payload,
                served_by="legacy",
                policy=policy,
                fallback_used=True,
                artifact_path=fallback_path,
                backend_mode=self.backend_mode,
            )

        summary_path = self.shadow.record_promotion_result(
            category=category,
            request_key=request_key,
            policy=policy,
            served_by="postgres",
            fallback_used=False,
            artifact_path=None,
        )
        return ExecutionResult(
            payload=postgres_payload,
            served_by="postgres",
            policy=policy,
            fallback_used=False,
            artifact_path=summary_path,
            backend_mode=self.backend_mode,
        )

    def execute_write(
        self,
        request: Request,
        category: str,
        operation: Callable[[], dict[str, Any]],
        *,
        extra: dict[str, Any] | None = None,
        postgres_mutator: Callable[[], dict[str, Any]] | None = None,
    ) -> ExecutionResult:
        policy = self.policy_for(category)
        request_key = self.request_key(request, extra)

        if self.backend_mode == "legacy" or policy in {POLICY_LEGACY_ONLY, POLICY_SHADOW_COMPARE} or postgres_mutator is None:
            payload = operation()
            artifact_path: Path | None = None
            if self.shadow_enabled:
                artifact = self.shadow.observe_write(category, request_key, payload)
                if artifact and artifact.get("artifact_path"):
                    artifact_path = Path(str(artifact["artifact_path"]))
            return ExecutionResult(
                payload=payload,
                served_by="legacy",
                policy=policy,
                fallback_used=False,
                artifact_path=artifact_path,
                backend_mode=self.backend_mode,
            )

        try:
            self.shadow.sync_from_source(reason=f"write-promoted-init:{category}", force=False)
            with self.deterministic_write_context(request_key):
                postgres_payload = postgres_mutator()
        except Exception as exc:
            payload = operation()
            artifact_path: Path | None = None
            if self.shadow_enabled:
                artifact = self.shadow.observe_write(category, request_key, payload)
                if artifact and artifact.get("artifact_path"):
                    artifact_path = Path(str(artifact["artifact_path"]))
            fallback_path = self.shadow.record_fallback_event(
                category=category,
                request_key=request_key,
                policy=policy,
                reason="postgres_unavailable",
                primary_backend="postgres",
                detail=str(exc),
                artifact_path=artifact_path,
            )
            self.shadow.sync_from_source(reason=f"write-fallback:{category}", force=True)
            return ExecutionResult(
                payload=payload,
                served_by="legacy",
                policy=policy,
                fallback_used=True,
                artifact_path=fallback_path,
                backend_mode=self.backend_mode,
            )

        try:
            with self.deterministic_write_context(request_key):
                legacy_payload = operation()
        except Exception:
            self.shadow.sync_from_source(reason=f"write-legacy-failed:{category}", force=True)
            raise
        artifact_path: Path | None = None

        if self.shadow_enabled:
            artifact = self.shadow.observe_write(category, request_key, legacy_payload)
            if artifact and artifact.get("artifact_path"):
                artifact_path = Path(str(artifact["artifact_path"]))

        normalized_legacy, normalized_postgres = self._normalized_compare_pair(legacy_payload, postgres_payload)
        diffs = diff_values(normalized_legacy, normalized_postgres)
        if diffs:
            mismatch_path = self.shadow.record_contract_mismatch(
                category=category,
                request_key=request_key,
                policy=policy,
                legacy_payload=legacy_payload,
                postgres_payload=postgres_payload,
                diffs=diffs,
            )
            fallback_path = self.shadow.record_fallback_event(
                category=category,
                request_key=request_key,
                policy=policy,
                reason="contract_mismatch",
                primary_backend="postgres",
                detail=f"{len(diffs)} mismatched paths",
                artifact_path=mismatch_path,
            )
            self.shadow.sync_from_source(reason=f"write-contract-mismatch:{category}", force=True)
            return ExecutionResult(
                payload=legacy_payload,
                served_by="legacy",
                policy=policy,
                fallback_used=True,
                artifact_path=fallback_path,
                backend_mode=self.backend_mode,
            )

        if not getattr(self.postgres, "native_authority", False):
            self.shadow.sync_from_source(reason=f"write-promoted:{category}", force=True)
        reconciliation_path, reconciliation = self.shadow.record_state_reconciliation(
            category=category,
            request_key=request_key,
        )
        if reconciliation.get("status") != "ok":
            fallback_path = self.shadow.record_fallback_event(
                category=category,
                request_key=request_key,
                policy=policy,
                reason="state_reconciliation_mismatch",
                primary_backend="postgres",
                detail=f"{len(reconciliation.get('diffs') or [])} reconciled state mismatches",
                artifact_path=reconciliation_path,
            )
            self.shadow.sync_from_source(reason=f"write-reconciliation-mismatch:{category}", force=True)
            return ExecutionResult(
                payload=legacy_payload,
                served_by="legacy",
                policy=policy,
                fallback_used=True,
                artifact_path=fallback_path,
                backend_mode=self.backend_mode,
            )
        summary_path = self.shadow.record_promotion_result(
            category=category,
            request_key=request_key,
            policy=policy,
            served_by="postgres",
            fallback_used=False,
            artifact_path=reconciliation_path,
        )
        return ExecutionResult(
            payload=postgres_payload,
            served_by="postgres",
            policy=policy,
            fallback_used=False,
            artifact_path=summary_path,
            backend_mode=self.backend_mode,
        )

    def observe_read(self, request: Request, category: str, payload: dict[str, Any], *, extra: dict[str, Any] | None = None) -> None:
        if not self.shadow_enabled:
            return
        self.shadow.observe_read(category, self.request_key(request, extra), payload)

    def observe_write(self, request: Request, category: str, payload: dict[str, Any], *, extra: dict[str, Any] | None = None) -> None:
        if not self.shadow_enabled:
            return
        self.shadow.observe_write(category, self.request_key(request, extra), payload)

    def observe_worker(self, category: str) -> None:
        if not self.shadow_enabled:
            return
        self.shadow.observe_worker_cycle(category)
