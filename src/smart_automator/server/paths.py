from __future__ import annotations

import os
from pathlib import Path


def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


PROJECT_ROOT = find_project_root()
ENV_FILE = PROJECT_ROOT / ".env"
WEBSITES_FILE = PROJECT_ROOT / "websites.json"
LLM_SETTINGS_FILE = PROJECT_ROOT / "llm_settings.json"
PRICING_FILE = PROJECT_ROOT / "pricing.json"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", str(PROJECT_ROOT / "data" / "screenshots")))
REPORT_DIR = Path(os.getenv("REPORT_DIR", str(PROJECT_ROOT / "data" / "reports")))
HISTORY_DIR = Path(os.getenv("HISTORY_DIR", str(PROJECT_ROOT / "data" / "histories")))
REPLAY_DIR = Path(os.getenv("REPLAY_DIR", str(PROJECT_ROOT / "data" / "replays")))
AUTH_DIR = Path(os.getenv("AUTH_DIR", str(PROJECT_ROOT / "data" / "auth")))
RUNS_DIR = Path(os.getenv("RUNS_DIR", str(PROJECT_ROOT / "data" / "runs")))
WEBSITES_DIR = Path(os.getenv("WEBSITES_DIR", str(PROJECT_ROOT / "data" / "websites")))
LLM_USER_DIR = Path(os.getenv("LLM_USER_DIR", str(PROJECT_ROOT / "data" / "llm")))
USERS_FILE = AUTH_DIR / "users.json"
SESSIONS_FILE = AUTH_DIR / "sessions.json"
WORKER_TOKENS_FILE = AUTH_DIR / "worker_tokens.json"
UI_DIST = PROJECT_ROOT / "ui" / "dist"
