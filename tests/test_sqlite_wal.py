"""SQLite WAL / busy_timeout / pool settings for concurrent API + run threads."""

from __future__ import annotations

from sqlalchemy.pool import NullPool

from smart_automator.db import reset_engine
from smart_automator.db.engine import get_engine, get_session
from smart_automator.db.models import Base


def test_file_sqlite_uses_wal_busy_timeout_and_null_pool(tmp_path) -> None:
    reset_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    engine = get_engine()
    Base.metadata.create_all(engine)
    assert isinstance(engine.pool, NullPool)

    with get_session() as session:
        mode = session.connection().exec_driver_sql("PRAGMA journal_mode").scalar()
        timeout = session.connection().exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert str(mode).lower() == "wal"
    assert int(timeout) >= 5000
