from __future__ import annotations

import json
from pathlib import Path

from ..agent.history import AgentStepHistory
from .paths import HISTORY_DIR


def history_path(run_id: str) -> Path:
    return HISTORY_DIR / f"{run_id}.json"


def save_run_history(run_id: str, history: AgentStepHistory) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = history_path(run_id)
    path.write_text(json.dumps(history.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete_run_history(run_id: str) -> None:
    path = history_path(run_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def load_run_history(run_id: str) -> AgentStepHistory | None:
    path = history_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return AgentStepHistory.from_dict(data)
