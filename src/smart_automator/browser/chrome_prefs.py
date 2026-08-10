from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def automation_chrome_args() -> list[str]:
    return [
        "--disable-features=PasswordLeakDetection,PasswordManagerLeakDetection",
        "--disable-save-password-bubble",
    ]


def apply_automation_chrome_prefs(
    user_data_dir: str,
    profile_subdirectory: str = "Default",
) -> None:
    profile_subdirectory = (profile_subdirectory or "Default").strip() or "Default"
    profile_dir = Path(user_data_dir).expanduser() / profile_subdirectory
    profile_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = profile_dir / "Preferences"

    prefs: dict = {}
    if prefs_path.is_file():
        try:
            loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prefs = loaded
        except json.JSONDecodeError:
            log.warning(
                "Corrupt Chrome Preferences at %s; applying automation prefs only",
                prefs_path,
            )

    prefs["credentials_enable_service"] = False
    profile = prefs.get("profile")
    if not isinstance(profile, dict):
        profile = {}
        prefs["profile"] = profile
    profile["password_manager_enabled"] = False
    profile["password_manager_leak_detection"] = False

    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
