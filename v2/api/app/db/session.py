from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.config import load_settings


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or load_settings()
    if settings.postgres_url.startswith("sqlite"):
        sqlite_target = settings.postgres_url.split("///", 1)[-1]
        Path(sqlite_target).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.postgres_url, future=True)


def build_session_factory(settings: Settings | None = None, engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or build_engine(settings), future=True)
