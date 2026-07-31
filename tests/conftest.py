"""Shared pytest fixtures for API tests with isolated auth and persistence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from smart_automator.server import app as app_module
from smart_automator.server import run_state
from smart_automator.server.auth import dependencies as auth_dependencies


@pytest.fixture(autouse=True)
def isolated_server_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_OPEN_REGISTER", "true")
    auth_dir = tmp_path / "auth"
    runs_dir = tmp_path / "runs"
    websites_dir = tmp_path / "websites"
    histories_dir = tmp_path / "histories"
    replays_dir = tmp_path / "replays"
    reports_dir = tmp_path / "reports"
    screenshots_dir = tmp_path / "screenshots"

    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", auth_dir / "users.json")
    monkeypatch.setattr("smart_automator.server.paths.SESSIONS_FILE", auth_dir / "sessions.json")
    monkeypatch.setattr("smart_automator.server.paths.RUNS_DIR", runs_dir)
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_DIR", websites_dir)
    monkeypatch.setattr("smart_automator.server.paths.HISTORY_DIR", histories_dir)
    monkeypatch.setattr("smart_automator.server.paths.REPLAY_DIR", replays_dir)
    monkeypatch.setattr("smart_automator.server.paths.REPORT_DIR", reports_dir)
    monkeypatch.setattr("smart_automator.server.paths.SCREENSHOT_DIR", screenshots_dir)

    auth_dependencies._user_store = None
    auth_dependencies._session_store = None
    run_state._runs.clear()

    yield


@pytest.fixture
def anon_client() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture
def auth_client(anon_client: TestClient) -> TestClient:
    res = anon_client.post(
        "/api/auth/register",
        json={"username": "tester", "password": "secret-pass"},
    )
    assert res.status_code == 201, res.text
    return anon_client


@pytest.fixture
def client(auth_client: TestClient) -> TestClient:
    """Authenticated API client for tests that expect the historical `client` name."""
    return auth_client


@pytest.fixture
def second_auth_client() -> TestClient:
    owner = TestClient(app_module.app)
    owner_res = owner.post(
        "/api/auth/register",
        json={"username": "owner", "password": "secret-pass"},
    )
    assert owner_res.status_code == 201, owner_res.text

    other = TestClient(app_module.app)
    other_res = other.post(
        "/api/auth/register",
        json={"username": "other", "password": "secret-pass"},
    )
    assert other_res.status_code == 201, other_res.text
    return other
