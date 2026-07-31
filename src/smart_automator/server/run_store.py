from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import paths


def run_record_path(user_id: str, run_id: str) -> Path:
    return paths.RUNS_DIR / user_id / f"{run_id}.json"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def save_run_record(user_id: str, run_id: str, data: dict[str, Any]) -> Path:
    path = run_record_path(user_id, run_id)
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


def load_run_record(user_id: str, run_id: str) -> dict[str, Any] | None:
    path = run_record_path(user_id, run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_run_records(user_id: str) -> list[dict[str, Any]]:
    user_dir = paths.RUNS_DIR / user_id
    if not user_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(user_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def user_owns_run_prefix(user_id: str, prefix: str) -> bool:
    """True if this user has a persisted run whose id starts with ``prefix``."""
    if not prefix or "/" in prefix or ".." in prefix:
        return False
    user_dir = paths.RUNS_DIR / user_id
    if not user_dir.is_dir():
        return False
    return any(user_dir.glob(f"{prefix}*.json"))


def delete_run_record(user_id: str, run_id: str) -> None:
    path = run_record_path(user_id, run_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
