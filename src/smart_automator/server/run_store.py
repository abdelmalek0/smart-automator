from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from ..db.engine import get_session
from ..db.models import RunRow
from . import paths


def run_record_path(user_id: str, run_id: str) -> Path:
    """Legacy path helper retained for callers that reference run file locations."""
    return paths.RUNS_DIR / user_id / f"{run_id}.json"


def save_run_record(user_id: str, run_id: str, data: dict[str, Any]) -> Path:
    status = str(data.get("status", "pending"))
    started_at = float(data.get("started_at", 0))
    finished_at = data.get("finished_at")
    with get_session() as session:
        row = session.get(RunRow, run_id)
        if row is None:
            session.add(
                RunRow(
                    run_id=run_id,
                    user_id=user_id,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    payload=data,
                )
            )
        else:
            row.user_id = user_id
            row.status = status
            row.started_at = started_at
            row.finished_at = finished_at
            row.payload = data
    return run_record_path(user_id, run_id)


def load_run_record(user_id: str, run_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        row = session.scalar(
            select(RunRow).where(RunRow.run_id == run_id, RunRow.user_id == user_id)
        )
        if row is None:
            return None
        payload = row.payload
        return dict(payload) if isinstance(payload, dict) else None


def list_run_records(user_id: str) -> list[dict[str, Any]]:
    with get_session() as session:
        rows = session.scalars(
            select(RunRow)
            .where(RunRow.user_id == user_id)
            .order_by(RunRow.started_at.desc())
        ).all()
        records: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row.payload, dict):
                records.append(dict(row.payload))
        return records


def user_owns_run_prefix(user_id: str, prefix: str) -> bool:
    """True if this user has a persisted run whose id starts with ``prefix``."""
    if not prefix or "/" in prefix or ".." in prefix:
        return False
    with get_session() as session:
        row = session.scalar(
            select(RunRow.run_id)
            .where(RunRow.user_id == user_id, RunRow.run_id.startswith(prefix))
            .limit(1)
        )
        return row is not None


def delete_run_record(user_id: str, run_id: str) -> None:
    with get_session() as session:
        session.execute(
            delete(RunRow).where(RunRow.run_id == run_id, RunRow.user_id == user_id)
        )
