from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

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


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def _is_sqlite_memory_url(url: str) -> bool:
    return ":memory:" in url or url in {"sqlite://", "sqlite:///"}


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def _configure_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        return
    url = get_database_url()
    kwargs: dict = {}
    if _is_sqlite_url(url):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 5.0}
        # QueuePool holds extra file connections and fights SQLite locking.
        # In-memory DBs must reuse one connection; files use NullPool + WAL.
        kwargs["poolclass"] = StaticPool if _is_sqlite_memory_url(url) else NullPool
    _engine = create_engine(url, **kwargs)
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
