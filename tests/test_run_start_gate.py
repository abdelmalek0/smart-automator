"""Tests for Connect/offline and one-at-a-time run start gating."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from smart_automator.server.app import _cancel_active_run
from smart_automator.server.run_state import RunState, add_run, get_run
from smart_automator.server.workers import connect_worker_busy

# Captured before api_run_test_harness replaces threading.Thread.
_RealThread = threading.Thread


@dataclass
class FakeWorker:
    online: bool = True
    browser_state: str = "idle"
    active_run_id: str | None = None
    lease_lock: threading.Lock = field(default_factory=threading.Lock)


class FakeRegistry:
    def __init__(self, worker: FakeWorker | None) -> None:
        self._worker = worker

    def get(self, _user_id: str) -> FakeWorker | None:
        if self._worker is None or not self._worker.online:
            return None
        return self._worker

    def request_browser_stop(self, *_args, **_kwargs) -> None:
        return None


def _start_payload() -> dict[str, object]:
    return {
        "task": "Open homepage",
        "success_criteria": "Page loads",
        "headless": True,
        "max_steps": 5,
    }


def test_start_run_rejects_when_connect_offline(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "smart_automator.server.workers.local_browser_mode_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(None),
    )

    res = client.post("/api/runs", json=_start_payload())
    assert res.status_code == 503
    assert res.json()["detail"] == "Connect app offline"


def test_start_run_allows_local_browser_without_connect(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "smart_automator.server.workers.local_browser_mode_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(None),
    )

    res = client.post("/api/runs", json=_start_payload())
    assert res.status_code == 201


def test_start_run_rejects_when_worker_busy(client: TestClient, monkeypatch) -> None:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    active = RunState(
        run_id="other-run",
        user_id=user_id,
        task="Existing",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    active.status = "running"
    add_run(active)

    worker = FakeWorker(browser_state="ready", active_run_id="other-run")
    monkeypatch.setattr(
        "smart_automator.server.workers.local_browser_mode_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(worker),
    )

    res = client.post("/api/runs", json=_start_payload())
    assert res.status_code == 409


def test_start_run_rejects_when_active_run_exists(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "smart_automator.server.workers.local_browser_mode_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(None),
    )

    user_id = client.get("/api/auth/me").json()["user"]["id"]
    active = RunState(
        run_id="active-run",
        user_id=user_id,
        task="Existing",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    active.status = "running"
    add_run(active)

    res = client.post("/api/runs", json=_start_payload())
    assert res.status_code == 409
    assert res.json()["detail"] == "Another run is already in progress"


def test_start_run_ignores_persisted_stale_running(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "smart_automator.server.workers.local_browser_mode_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(None),
    )

    user_id = client.get("/api/auth/me").json()["user"]["id"]
    stale = RunState(
        run_id="stale-disk-run",
        user_id=user_id,
        task="Crashed leftover",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    stale.status = "running"
    stale.persist()
    assert get_run(stale.run_id) is None

    res = client.post("/api/runs", json=_start_payload())
    assert res.status_code == 201


def test_concurrent_start_run_rejects_second(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "smart_automator.server.workers.local_browser_mode_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(None),
    )
    monkeypatch.setattr(
        "smart_automator.server.app.run_automation",
        lambda _run: None,
    )

    barrier = threading.Barrier(2)
    results: list[int] = []

    def _post() -> None:
        barrier.wait()
        results.append(client.post("/api/runs", json=_start_payload()).status_code)

    threads = [_RealThread(target=_post), _RealThread(target=_post)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [201, 409]
    second = client.post("/api/runs", json=_start_payload())
    assert second.status_code == 409
    assert second.json()["detail"] == "Another run is already in progress"


def test_connect_worker_busy_follows_browser_state(client: TestClient, monkeypatch) -> None:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    cancelled = RunState(
        run_id="cancelled-run",
        user_id=user_id,
        task="Cancelled",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    cancelled.status = "cancelled"
    add_run(cancelled)

    worker = FakeWorker(browser_state="ready", active_run_id="cancelled-run")
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: FakeRegistry(worker),
    )

    assert connect_worker_busy(user_id) is True
    worker.browser_state = "stopping"
    assert connect_worker_busy(user_id) is True
    worker.browser_state = "idle"
    worker.active_run_id = None
    assert connect_worker_busy(user_id) is False


def test_connect_worker_busy_expires_stuck_stopping(client: TestClient, monkeypatch) -> None:
    import time

    from smart_automator.server.workers import WorkerConnection, WorkerRegistry

    user_id = client.get("/api/auth/me").json()["user"]["id"]
    registry = WorkerRegistry()
    worker = WorkerConnection(user_id=user_id, websocket=MagicMock(), loop=MagicMock())
    registry.register(worker)
    worker.browser_state = "stopping"
    worker.active_run_id = "stale-run"
    worker.stop_deadline = time.monotonic() - 1
    monkeypatch.setattr(
        "smart_automator.server.workers.worker_registry",
        lambda: registry,
    )
    with monkeypatch.context() as patched:
        patched.setattr(WorkerRegistry, "_teardown_proxy", lambda *args, **kwargs: None)
        assert connect_worker_busy(user_id) is False
    assert worker.browser_state == "idle"
    assert worker.active_run_id is None


def test_cancel_active_run_stops_connect_browser(client: TestClient, monkeypatch) -> None:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="run-cancel",
        user_id=user_id,
        task="Cancel me",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    run.status = "running"
    add_run(run)

    registry = MagicMock()
    monkeypatch.setattr("smart_automator.server.app.worker_registry", lambda: registry)

    _cancel_active_run(run)

    registry.request_browser_stop.assert_called_once_with(
        user_id,
        run_id="run-cancel",
        wait=False,
    )
    assert run.status == "cancelled"
