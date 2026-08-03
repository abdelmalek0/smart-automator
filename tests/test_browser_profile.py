"""Tests for browser profile resolution and config API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smart_automator.browser.chrome_profile_mirror import (
    chrome_profile_mirror_path,
    resolve_persistent_launch_dir,
    sync_chrome_profile,
)
from smart_automator.browser.chrome_profiles import (
    ChromeProfile,
    discover_chrome_profiles,
    format_effective_chrome_profile,
    is_system_chrome_user_data_dir,
)
from smart_automator.browser.context import BrowserContext
from smart_automator.config import (
    browser_session_mode,
    default_chrome_user_data,
    normalize_browser_overrides,
    resolve_chrome_user_data,
)
from smart_automator.server.app import app


def test_resolve_chrome_user_data_uses_default_when_not_fresh() -> None:
    resolved = resolve_chrome_user_data("", fresh_profile=False)
    assert resolved == default_chrome_user_data()


def test_resolve_chrome_user_data_honors_explicit_path() -> None:
    resolved = resolve_chrome_user_data("/tmp/my-profile", fresh_profile=False)
    assert resolved == "/tmp/my-profile"


def test_resolve_chrome_user_data_empty_when_fresh() -> None:
    resolved = resolve_chrome_user_data("/tmp/my-profile", fresh_profile=True)
    assert resolved == ""


def test_browser_session_mode_priority() -> None:
    assert browser_session_mode(cdp_url="ws://127.0.0.1:9222", fresh_profile=False) == "cdp"
    assert browser_session_mode(cdp_url="", fresh_profile=True) == "ephemeral"
    assert browser_session_mode(cdp_url="", fresh_profile=False) == "persistent"


def test_normalize_browser_overrides_keeps_fresh_profile_with_cdp() -> None:
    cdp, fresh = normalize_browser_overrides(
        cdp_url=" ws://127.0.0.1:9222 ",
        fresh_profile=True,
    )
    assert cdp == "ws://127.0.0.1:9222"
    assert fresh is True


def test_normalize_browser_overrides_preserves_fresh_profile_without_cdp() -> None:
    cdp, fresh = normalize_browser_overrides(cdp_url="", fresh_profile=True)
    assert cdp == ""
    assert fresh is True


def test_format_effective_chrome_profile_includes_named_profile() -> None:
    assert format_effective_chrome_profile(
        "/home/user/.config/google-chrome",
        profile_directory="Profile 1",
    ) == "/home/user/.config/google-chrome (profile: Profile 1)"


def test_discover_chrome_profiles_from_local_state(tmp_path, monkeypatch) -> None:
    chrome_root = tmp_path / "google-chrome"
    chrome_root.mkdir()
    (chrome_root / "Local State").write_text(
        json.dumps(
            {
                "profile": {
                    "info_cache": {
                        "Default": {"name": "Person 1"},
                        "Profile 1": {"name": "Work"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chrome", str(chrome_root))],
    )

    profiles = discover_chrome_profiles()
    assert len(profiles) == 2
    assert profiles[0] == ChromeProfile(
        id=f"{chrome_root}|Default",
        browser="Chrome",
        name="Person 1",
        user_data_dir=str(chrome_root),
        profile_directory="Default",
    )
    assert profiles[1].name == "Work"
    assert profiles[1].profile_directory == "Profile 1"


def test_discover_chrome_profiles_falls_back_to_preferences_dirs(tmp_path, monkeypatch) -> None:
    chrome_root = tmp_path / "chromium"
    default_dir = chrome_root / "Default"
    default_dir.mkdir(parents=True)
    (default_dir / "Preferences").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chromium", str(chrome_root))],
    )

    profiles = discover_chrome_profiles()
    assert len(profiles) == 1
    assert profiles[0].profile_directory == "Default"
    assert profiles[0].name == "Default"


def test_is_system_chrome_user_data_dir_recognizes_known_roots(tmp_path, monkeypatch) -> None:
    chrome_root = tmp_path / "google-chrome"
    chrome_root.mkdir()
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chrome", str(chrome_root))],
    )

    assert is_system_chrome_user_data_dir(str(chrome_root)) is True
    assert is_system_chrome_user_data_dir(str(tmp_path / "other")) is False


def test_sync_chrome_profile_copies_profile_and_skips_cache(tmp_path, monkeypatch) -> None:
    chrome_root = tmp_path / "chrome"
    source_profile = chrome_root / "Default"
    cache_dir = source_profile / "Cache"
    source_profile.mkdir(parents=True)
    cache_dir.mkdir()
    (source_profile / "Preferences").write_text("{}", encoding="utf-8")
    (cache_dir / "data").write_text("cache", encoding="utf-8")

    mirror_base = tmp_path / "mirrors"
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profile_mirror.DEFAULT_CHROME_PROFILE_DIR",
        mirror_base,
    )

    mirror_path = sync_chrome_profile(str(chrome_root), "Default")
    assert mirror_path.exists()
    assert (mirror_path / "Default" / "Preferences").is_file()
    assert not (mirror_path / "Default" / "Cache").exists()
    assert (mirror_path / "Local State").is_file()


def test_resolve_persistent_launch_dir_mirrors_system_profile(tmp_path, monkeypatch) -> None:
    chrome_root = tmp_path / "chrome"
    profile_dir = chrome_root / "Profile 1"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Preferences").write_text("{}", encoding="utf-8")

    mirror_base = tmp_path / "mirrors"
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profile_mirror.DEFAULT_CHROME_PROFILE_DIR",
        mirror_base,
    )
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chrome", str(chrome_root))],
    )

    launch_dir, launch_profile_dir = resolve_persistent_launch_dir(str(chrome_root), "Profile 1")
    assert launch_profile_dir == ""
    assert launch_dir.startswith(str(mirror_base))
    assert (Path(launch_dir) / "Default" / "Preferences").is_file()


def test_resolve_persistent_launch_dir_passthrough_for_custom_path() -> None:
    launch_dir, launch_profile_dir = resolve_persistent_launch_dir(
        "/tmp/custom-profile",
        "Profile 1",
    )
    assert launch_dir == "/tmp/custom-profile"
    assert launch_profile_dir == "Profile 1"


def test_resolve_persistent_launch_dir_rejects_system_root_without_profile(tmp_path, monkeypatch) -> None:
    chrome_root = tmp_path / "chrome"
    chrome_root.mkdir()
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chrome", str(chrome_root))],
    )

    with pytest.raises(ValueError, match="named profile"):
        resolve_persistent_launch_dir(str(chrome_root), "")


def test_launch_uses_resolved_profile_dir_when_not_fresh() -> None:
    from smart_automator.config import Config

    config = Config(chrome_user_data="", fresh_profile=False)
    context = BrowserContext(config)
    captured: dict[str, str] = {}

    mock_playwright = MagicMock()
    mock_persistent = MagicMock()
    mock_persistent.browser = MagicMock()
    mock_playwright.chromium.launch_persistent_context.return_value = mock_persistent

    with patch("smart_automator.browser.context.sync_playwright") as sync_pw:
        sync_pw.return_value.start.return_value = mock_playwright
        context.launch(fresh_profile=False)

    mock_playwright.chromium.launch_persistent_context.assert_called_once()
    call_args = mock_playwright.chromium.launch_persistent_context.call_args
    captured["dir"] = call_args.args[0]
    assert captured["dir"] == default_chrome_user_data()
    assert "args" not in call_args.kwargs or "--profile-directory=" not in str(
        call_args.kwargs.get("args", [])
    )
    mock_playwright.chromium.launch.assert_not_called()


def test_launch_passes_profile_directory_arg_for_custom_non_system_path() -> None:
    from smart_automator.config import Config

    config = Config(
        chrome_user_data="/tmp/custom-chrome",
        chrome_profile_directory="Profile 1",
        fresh_profile=False,
    )
    context = BrowserContext(config)

    mock_playwright = MagicMock()
    mock_persistent = MagicMock()
    mock_persistent.browser = MagicMock()
    mock_playwright.chromium.launch_persistent_context.return_value = mock_persistent

    with patch("smart_automator.browser.context.sync_playwright") as sync_pw:
        sync_pw.return_value.start.return_value = mock_playwright
        context.launch(fresh_profile=False)

    call_args = mock_playwright.chromium.launch_persistent_context.call_args
    assert call_args.args[0] == "/tmp/custom-chrome"
    assert call_args.kwargs["args"] == ["--profile-directory=Profile 1"]


def test_launch_uses_mirror_for_system_chrome_profile(tmp_path, monkeypatch) -> None:
    from smart_automator.config import Config

    chrome_root = tmp_path / "chrome"
    profile_dir = chrome_root / "Default"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Preferences").write_text("{}", encoding="utf-8")
    mirror_base = tmp_path / "mirrors"

    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chrome", str(chrome_root))],
    )
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profile_mirror.DEFAULT_CHROME_PROFILE_DIR",
        mirror_base,
    )

    config = Config(
        chrome_user_data=str(chrome_root),
        chrome_profile_directory="Default",
        fresh_profile=False,
    )
    context = BrowserContext(config)

    mock_playwright = MagicMock()
    mock_persistent = MagicMock()
    mock_persistent.browser = MagicMock()
    mock_playwright.chromium.launch_persistent_context.return_value = mock_persistent

    with patch("smart_automator.browser.context.sync_playwright") as sync_pw:
        sync_pw.return_value.start.return_value = mock_playwright
        context.launch(fresh_profile=False)

    call_args = mock_playwright.chromium.launch_persistent_context.call_args
    launch_dir = call_args.args[0]
    assert launch_dir.startswith(str(mirror_base))
    assert "--profile-directory=" not in str(call_args.kwargs.get("args", []))


def test_launch_skips_persistent_context_when_fresh() -> None:
    from smart_automator.config import Config

    config = Config(chrome_user_data="", fresh_profile=False)
    context = BrowserContext(config)

    mock_playwright = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser

    with patch("smart_automator.browser.context.sync_playwright") as sync_pw:
        sync_pw.return_value.start.return_value = mock_playwright
        context.launch(fresh_profile=True)

    mock_playwright.chromium.launch_persistent_context.assert_not_called()
    mock_playwright.chromium.launch.assert_called_once()


def test_config_response_includes_browser_session_fields(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "QA_FRESH_PROFILE=false\nCHROME_USER_DATA=\nCHROME_PROFILE_DIRECTORY=\nCDP_URL=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("smart_automator.server.config_service.ENV_FILE", env_file)

    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["browser_session_mode"] == "persistent"
    assert body["effective_chrome_user_data"] == default_chrome_user_data()
    assert body["effective_chrome_profile"] == default_chrome_user_data()
    assert body["default_chrome_user_data"] == default_chrome_user_data()
    assert body["chrome_profile_directory"] == ""
    assert body["chrome_profile_mirror_path"] == ""
    assert body["cdp_url"] == ""


def test_config_response_includes_mirror_path_for_system_profile(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    chrome_root = tmp_path / "chrome"
    chrome_root.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CHROME_USER_DATA={chrome_root}\nCHROME_PROFILE_DIRECTORY=Default\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("smart_automator.server.config_service.ENV_FILE", env_file)
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profiles._CHROME_ROOTS",
        [("Chrome", str(chrome_root))],
    )
    monkeypatch.setattr(
        "smart_automator.browser.chrome_profile_mirror.DEFAULT_CHROME_PROFILE_DIR",
        tmp_path / "mirrors",
    )

    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["chrome_profile_mirror_path"]
    assert "mirrored to" in body["effective_chrome_profile"]
    assert body["chrome_profile_mirror_path"] == chrome_profile_mirror_path(
        str(chrome_root),
        "Default",
    )


def test_config_update_round_trips_chrome_profile_directory(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=groq\n", encoding="utf-8")
    monkeypatch.setattr("smart_automator.server.config_service.ENV_FILE", env_file)

    res = client.put(
        "/api/config",
        json={
            "chrome_user_data": "/home/user/.config/google-chrome",
            "chrome_profile_directory": "Profile 1",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["chrome_user_data"] == "/home/user/.config/google-chrome"
    assert body["chrome_profile_directory"] == "Profile 1"
    assert body["effective_chrome_profile"] == (
        "/home/user/.config/google-chrome (profile: Profile 1)"
    )


def test_config_update_keeps_fresh_profile_when_cdp_url_set(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=groq\nQA_FRESH_PROFILE=true\nCDP_URL=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("smart_automator.server.config_service.ENV_FILE", env_file)

    res = client.put(
        "/api/config",
        json={
            "cdp_url": "ws://127.0.0.1:9222",
            "fresh_profile": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["cdp_url"] == "ws://127.0.0.1:9222"
    assert body["fresh_profile"] is True
    assert body["browser_session_mode"] == "cdp"

    get_res = client.get("/api/config")
    assert get_res.status_code == 200
    assert get_res.json()["fresh_profile"] is True


def test_list_chrome_profiles_endpoint(client: TestClient, monkeypatch) -> None:
    sample = [
        {
            "id": "/tmp/chrome|Default",
            "browser": "Chrome",
            "name": "Person 1",
            "user_data_dir": "/tmp/chrome",
            "profile_directory": "Default",
        }
    ]

    class FakeRegistry:
        def get(self, _user_id):
            return object()

        def profiles_for_user(self, _user_id):
            return sample

    monkeypatch.setattr(
        "smart_automator.server.app.worker_registry",
        lambda: FakeRegistry(),
    )
    monkeypatch.setattr(
        "smart_automator.server.app.local_browser_mode_enabled",
        lambda: False,
    )

    res = client.get("/api/chrome-profiles")
    assert res.status_code == 200
    assert res.json() == sample
