"""Shared pytest fixtures for API tests with isolated auth and persistence."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from smart_automator.db import init_db, reset_engine
from smart_automator.server import app as app_module
from smart_automator.server import run_state
from smart_automator.server.auth import dependencies as auth_dependencies


@pytest.fixture
def api_run_test_harness(monkeypatch):
    """Keep sequential start_run API tests valid under run-start gating."""
    monkeypatch.setenv("SMART_AUTOMATOR_LOCAL_BROWSER", "true")

    def stub_run_automation(run) -> None:
        run.status = "error"
        run.summary = "stubbed test run"
        run.finished_at = time.time()

    monkeypatch.setattr(app_module, "run_automation", stub_run_automation)

    real_thread = app_module.threading.Thread

    class ImmediateThread:
        def __init__(
            self,
            group=None,
            target=None,
            name=None,
            args=(),
            kwargs=None,
            *,
            daemon=None,
        ):
            self._target = target
            self._args = args or ()
            self._kwargs = kwargs or {}
            self._real = None
            # Patching threading.Thread is global; asyncio.to_thread pool workers
            # must still be real threads.
            if target is not stub_run_automation:
                self._real = real_thread(
                    group=group,
                    target=target,
                    name=name,
                    args=args,
                    kwargs=kwargs,
                    daemon=daemon,
                )

        def start(self) -> None:
            if self._real is not None:
                self._real.start()
                return
            if self._target:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)


@pytest.fixture(autouse=True)
def isolated_server_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_OPEN_REGISTER", "true")
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    websites_dir = tmp_path / "websites"
    websites_dir.mkdir()
    histories_dir = tmp_path / "histories"
    replays_dir = tmp_path / "replays"
    reports_dir = tmp_path / "reports"
    screenshots_dir = tmp_path / "screenshots"
    legacy_websites = tmp_path / "websites.json"
    llm_user_dir = tmp_path / "llm"

    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", auth_dir / "users.json")
    monkeypatch.setattr("smart_automator.server.paths.SESSIONS_FILE", auth_dir / "sessions.json")
    monkeypatch.setattr("smart_automator.server.paths.WORKER_TOKENS_FILE", auth_dir / "worker_tokens.json")
    monkeypatch.setattr("smart_automator.server.paths.RUNS_DIR", runs_dir)
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_DIR", websites_dir)
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_FILE", legacy_websites)
    monkeypatch.setattr("smart_automator.server.paths.LLM_USER_DIR", llm_user_dir)
    monkeypatch.setattr(
        "smart_automator.server.paths.LLM_SETTINGS_FILE", tmp_path / "llm_settings.json"
    )
    monkeypatch.setattr("smart_automator.server.paths.PRICING_FILE", tmp_path / "pricing.json")
    monkeypatch.setattr("smart_automator.storage.llm_settings.LLM_SETTINGS_FILE", tmp_path / "llm_settings.json")
    monkeypatch.setattr("smart_automator.server.paths.HISTORY_DIR", histories_dir)
    monkeypatch.setattr("smart_automator.server.paths.REPLAY_DIR", replays_dir)
    monkeypatch.setattr("smart_automator.server.paths.REPORT_DIR", reports_dir)
    monkeypatch.setattr("smart_automator.server.paths.SCREENSHOT_DIR", screenshots_dir)

    db_path = tmp_path / "test.db"
    reset_engine(f"sqlite:///{db_path}")
    init_db()

    auth_dependencies._user_store = None
    auth_dependencies._session_store = None
    run_state._runs.clear()

    yield


@pytest.fixture
def anon_client() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture
def auth_client(anon_client: TestClient, api_run_test_harness) -> TestClient:
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
def second_auth_client(api_run_test_harness) -> TestClient:
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
