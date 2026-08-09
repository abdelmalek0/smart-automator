from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..server.paths import PROJECT_ROOT

if TYPE_CHECKING:
    from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    db_file = os.getenv("DATABASE_FILE")
    if db_file:
        return f"sqlite:///{db_file}"
    db_path = PROJECT_ROOT / "data" / "smart_automator.db"
    return f"sqlite:///{db_path}"


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _configure_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        return
    url = get_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_engine() -> Engine:
    _configure_engine()
    assert _engine is not None
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Reset the engine (used by tests to point at an isolated database)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url is not None:
        os.environ["DATABASE_URL"] = url
    else:
        os.environ.pop("DATABASE_URL", None)


@contextmanager
def get_session():
    _configure_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from .migrate_json import cleanup_migrated_json_files, migrate_json_if_needed, migrate_schema_if_needed
    from .models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    migrate_schema_if_needed()
    migrate_json_if_needed()
    cleanup_migrated_json_files()
