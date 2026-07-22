from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import REPLAY_DIR


def replay_json_path(run_id: str) -> Path:
    return REPLAY_DIR / f"{run_id}.json"


def replay_script_path(run_id: str) -> Path:
    return REPLAY_DIR / f"{run_id}.py"


def save_run_replay(
    run_id: str,
    replay_steps: list[dict[str, Any]],
    replay_script: str,
) -> Path:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "replay_steps": replay_steps,
        "replay_script": replay_script,
    }
    path = replay_json_path(run_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    replay_script_path(run_id).write_text(replay_script, encoding="utf-8")
    return path


def has_replay_script(run_id: str) -> bool:
    return load_run_replay(run_id) is not None


def load_run_replay(run_id: str) -> dict[str, Any] | None:
    path = replay_json_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    steps = data.get("replay_steps")
    if not isinstance(steps, list):
        return None
    return data
