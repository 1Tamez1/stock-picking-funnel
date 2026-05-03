from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy import select

from app.db.models import OwnerApiToken
from app.db.models import OwnerUser
from app.db.models import UserSession
from app.shadow import SHADOW_WORKSPACE_ID
from app.shadow import ShadowBackend
from app.shadow import now_utc


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds")


def _ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return derived.hex()


def verify_password(password: str, salt_hex: str, password_hash: str) -> bool:
    candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, password_hash)


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def api_token_prefix(token: str) -> str:
    return token[:12]


@dataclass(slots=True)
class SessionPayload:
    required: bool
    authenticated: bool
    user_id: int | None = None
    email: str = ""
    display_name: str = ""
    expires_at: str = ""
    auth_method: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "required": self.required,
            "authenticated": self.authenticated,
        }
        if self.authenticated:
            payload["user"] = {
                "id": self.user_id,
                "email": self.email,
                "display_name": self.display_name,
            }
            payload["expires_at"] = self.expires_at
        return payload


class AuthService:
    def __init__(self, shadow: ShadowBackend):
        self.shadow = shadow
        self.settings = shadow.settings

    def _session(self):
        self.shadow.ensure_schema()
        return self.shadow.session_factory()()

    def auth_required(self) -> bool:
        session = self._session()
        try:
            owner = session.execute(select(OwnerUser.id).where(OwnerUser.is_active.is_(True)).limit(1)).scalar_one_or_none()
            return owner is not None
        finally:
            session.close()

    def ensure_seed_owner(self) -> None:
        if not self.settings.owner_seed_email or not self.settings.owner_seed_password:
            return
        if self.auth_required():
            return
        self.bootstrap_owner(
            email=self.settings.owner_seed_email,
            password=self.settings.owner_seed_password,
            display_name=self.settings.owner_seed_name,
        )

    def bootstrap_owner(self, *, email: str, password: str, display_name: str) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("Owner email is required.")
        if not password:
            raise ValueError("Owner password is required.")
        salt_hex = secrets.token_hex(16)
        session = self._session()
        try:
            session.execute(delete(OwnerApiToken))
            session.execute(delete(UserSession))
            session.execute(delete(OwnerUser))
            timestamp = now_utc()
            owner = OwnerUser(
                workspace_id=SHADOW_WORKSPACE_ID,
                email=normalized_email,
                display_name=display_name.strip() or "Owner",
                password_salt=salt_hex,
                password_hash=hash_password(password, salt_hex),
                is_active=True,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(owner)
            session.commit()
            return {
                "owner": {
                    "id": int(owner.id),
                    "email": owner.email,
                    "display_name": owner.display_name,
                    "created_at": _timestamp(owner.created_at),
                }
            }
        finally:
            session.close()

    def _load_valid_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        session = self._session()
        try:
            record = session.execute(
                select(UserSession, OwnerUser)
                .join(OwnerUser, OwnerUser.id == UserSession.user_id)
                .where(UserSession.session_token_hash == session_token_hash(token))
            ).first()
            if record is None:
                return None
            auth_session, user = record
            now = now_utc()
            revoked_at = _ensure_utc_datetime(auth_session.revoked_at)
            expires_at = _ensure_utc_datetime(auth_session.expires_at)
            if revoked_at is not None or expires_at is None or expires_at <= now or not user.is_active:
                return None
            auth_session.last_seen_at = now
            auth_session.updated_at = now
            session.commit()
            return {
                "user_id": int(user.id),
                "email": str(user.email or ""),
                "display_name": str(user.display_name or ""),
                "expires_at": _timestamp(expires_at),
                "auth_method": "session",
            }
        finally:
            session.close()

    def _load_valid_api_token(self, raw_token: str | None) -> dict[str, Any] | None:
        if not raw_token:
            return None
        session = self._session()
        try:
            record = session.execute(
                select(OwnerApiToken, OwnerUser)
                .join(OwnerUser, OwnerUser.id == OwnerApiToken.user_id)
                .where(
                    OwnerApiToken.token_prefix == api_token_prefix(raw_token),
                    OwnerApiToken.token_hash == session_token_hash(raw_token),
                )
            ).first()
            if record is None:
                return None
            api_token, user = record
            now = now_utc()
            revoked_at = _ensure_utc_datetime(api_token.revoked_at)
            expires_at = _ensure_utc_datetime(api_token.expires_at)
            if revoked_at is not None or (expires_at is not None and expires_at <= now) or not user.is_active:
                return None
            api_token.last_used_at = now
            api_token.updated_at = now
            session.commit()
            return {
                "user_id": int(user.id),
                "email": str(user.email or ""),
                "display_name": str(user.display_name or ""),
                "expires_at": _timestamp(expires_at),
                "auth_method": "bearer",
            }
        finally:
            session.close()

    def _bearer_token_from_request(self, request: Request) -> str | None:
        authorization = request.headers.get("authorization", "").strip()
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return token.strip() or None

    def session_from_request(self, request: Request) -> SessionPayload:
        required = self.auth_required()
        if not required:
            return SessionPayload(required=False, authenticated=False)
        loaded = self._load_valid_api_token(self._bearer_token_from_request(request))
        if loaded is None:
            token = request.cookies.get(self.settings.session_cookie_name)
            loaded = self._load_valid_session(token)
        if loaded is None:
            return SessionPayload(required=True, authenticated=False)
        return SessionPayload(
            required=True,
            authenticated=True,
            user_id=int(loaded["user_id"]),
            email=str(loaded["email"]),
            display_name=str(loaded["display_name"]),
            expires_at=str(loaded["expires_at"]),
            auth_method=str(loaded.get("auth_method") or ""),
        )

    def login(self, *, email: str, password: str, request: Request) -> tuple[str, dict[str, Any]]:
        normalized_email = email.strip().lower()
        session = self._session()
        try:
            user = session.execute(
                select(OwnerUser).where(OwnerUser.email == normalized_email, OwnerUser.is_active.is_(True))
            ).scalar_one_or_none()
            if user is None or not verify_password(password, user.password_salt, user.password_hash):
                raise ValueError("Invalid email or password.")
            now = now_utc()
            raw_token = secrets.token_urlsafe(32)
            auth_session = UserSession(
                user_id=int(user.id),
                session_token_hash=session_token_hash(raw_token),
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=self.settings.session_ttl_seconds),
                last_seen_at=now,
                revoked_at=None,
                ip_address=request.client.host if request.client else "",
                user_agent=request.headers.get("user-agent", "")[:1024],
            )
            session.add(auth_session)
            session.commit()
            return raw_token, SessionPayload(
                required=True,
                authenticated=True,
                user_id=int(user.id),
                email=user.email,
                display_name=user.display_name,
                expires_at=_timestamp(auth_session.expires_at),
            ).as_dict()
        finally:
            session.close()

    def logout(self, request: Request) -> dict[str, Any]:
        token = request.cookies.get(self.settings.session_cookie_name)
        if token:
            session = self._session()
            try:
                record = session.execute(
                    select(UserSession).where(UserSession.session_token_hash == session_token_hash(token))
                ).scalar_one_or_none()
                if record is not None:
                    record.revoked_at = now_utc()
                    record.updated_at = now_utc()
                    session.commit()
            finally:
                session.close()
        return {"ok": True}

    def issue_api_token(self, *, label: str, expires_in_days: int | None = None) -> dict[str, Any]:
        normalized_label = label.strip() or "Agent Token"
        session = self._session()
        try:
            user = session.execute(
                select(OwnerUser).where(OwnerUser.is_active.is_(True)).order_by(OwnerUser.id).limit(1)
            ).scalar_one_or_none()
            if user is None:
                raise ValueError("Bootstrap the owner account before issuing API tokens.")
            now = now_utc()
            raw_token = f"fvl2_{secrets.token_urlsafe(36)}"
            expires_at = now + timedelta(days=expires_in_days) if expires_in_days and expires_in_days > 0 else None
            record = OwnerApiToken(
                user_id=int(user.id),
                label=normalized_label,
                token_prefix=api_token_prefix(raw_token),
                token_hash=session_token_hash(raw_token),
                created_at=now,
                updated_at=now,
                last_used_at=None,
                expires_at=expires_at,
                revoked_at=None,
            )
            session.add(record)
            session.commit()
            return {
                "token": raw_token,
                "token_metadata": {
                    "id": int(record.id),
                    "label": record.label,
                    "token_prefix": record.token_prefix,
                    "created_at": _timestamp(record.created_at),
                    "expires_at": _timestamp(record.expires_at),
                    "revoked_at": _timestamp(record.revoked_at),
                },
            }
        finally:
            session.close()

    def list_api_tokens(self) -> dict[str, Any]:
        session = self._session()
        try:
            rows = session.execute(select(OwnerApiToken).order_by(OwnerApiToken.id)).scalars().all()
            return {
                "tokens": [
                    {
                        "id": int(row.id),
                        "label": row.label,
                        "token_prefix": row.token_prefix,
                        "created_at": _timestamp(row.created_at),
                        "updated_at": _timestamp(row.updated_at),
                        "last_used_at": _timestamp(row.last_used_at),
                        "expires_at": _timestamp(row.expires_at),
                        "revoked_at": _timestamp(row.revoked_at),
                    }
                    for row in rows
                ]
            }
        finally:
            session.close()

    def revoke_api_token(self, *, token_id: int | None = None, token_prefix: str = "") -> dict[str, Any]:
        if token_id is None and not token_prefix.strip():
            raise ValueError("Provide token_id or token_prefix.")
        session = self._session()
        try:
            query = select(OwnerApiToken)
            if token_id is not None:
                query = query.where(OwnerApiToken.id == token_id)
            else:
                query = query.where(OwnerApiToken.token_prefix == token_prefix.strip())
            record = session.execute(query).scalar_one_or_none()
            if record is None:
                raise KeyError("API token not found.")
            now = now_utc()
            record.revoked_at = now
            record.updated_at = now
            session.commit()
            return {
                "token": {
                    "id": int(record.id),
                    "label": record.label,
                    "token_prefix": record.token_prefix,
                    "revoked_at": _timestamp(record.revoked_at),
                }
            }
        finally:
            session.close()
