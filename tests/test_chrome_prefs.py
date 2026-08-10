"""Tests for Chrome automation preference patching."""

from __future__ import annotations

import json

from smart_automator.browser.chrome_prefs import apply_automation_chrome_prefs


def test_apply_automation_chrome_prefs_writes_defaults_for_missing_file(tmp_path) -> None:
    profile_dir = tmp_path / "Default"
    profile_dir.mkdir()

    apply_automation_chrome_prefs(str(tmp_path), "Default")

    prefs = json.loads((profile_dir / "Preferences").read_text(encoding="utf-8"))
    assert prefs["credentials_enable_service"] is False
    assert prefs["profile"]["password_manager_enabled"] is False
    assert prefs["profile"]["password_manager_leak_detection"] is False


def test_apply_automation_chrome_prefs_patches_existing_values(tmp_path) -> None:
    profile_dir = tmp_path / "Default"
    profile_dir.mkdir()
    (profile_dir / "Preferences").write_text(
        json.dumps(
            {
                "credentials_enable_service": True,
                "profile": {
                    "password_manager_enabled": True,
                    "password_manager_leak_detection": True,
                },
            }
        ),
        encoding="utf-8",
    )

    apply_automation_chrome_prefs(str(tmp_path), "Default")

    prefs = json.loads((profile_dir / "Preferences").read_text(encoding="utf-8"))
    assert prefs["credentials_enable_service"] is False
    assert prefs["profile"]["password_manager_enabled"] is False
    assert prefs["profile"]["password_manager_leak_detection"] is False
