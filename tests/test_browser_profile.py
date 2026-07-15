"""Tests for browser profile resolution and config API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from smart_automator.browser.context import BrowserContext
from smart_automator.config import (
    browser_session_mode,
    default_chrome_user_data,
    resolve_chrome_user_data,
)
from smart_automator.server.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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
    mock_playwright.chromium.launch.assert_not_called()


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
        "QA_FRESH_PROFILE=false\nCHROME_USER_DATA=\nCDP_URL=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("smart_automator.server.config_service.ENV_FILE", env_file)

    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["browser_session_mode"] == "persistent"
    assert body["effective_chrome_user_data"] == default_chrome_user_data()
    assert body["default_chrome_user_data"] == default_chrome_user_data()
    assert body["cdp_url"] == ""
