"""Tests for run purge (hard delete) API."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from smart_automator.server.app import app
from smart_automator.server.history_store import history_path, save_run_history
from smart_automator.server.replay_store import replay_json_path, save_run_replay
from smart_automator.server.run_state import RunState, add_run, get_run
from smart_automator.agent.history import AgentStepHistory


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_purge_run_removes_from_memory(client: TestClient) -> None:
    run = RunState(
        run_id="test-purge-run-id",
        task="Smoke test",
        headless=True,
        max_steps=10,
        success_criteria="Page loads",
    )
    run.status = "pass"
    run.finished_at = time.time()
    add_run(run)

    res = client.delete("/api/runs/test-purge-run-id?purge=true")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert get_run("test-purge-run-id") is None

    list_res = client.get("/api/runs")
    assert all(item["run_id"] != "test-purge-run-id" for item in list_res.json())

    get_res = client.get("/api/runs/test-purge-run-id")
    assert get_res.status_code == 404


def test_purge_run_deletes_artifacts(client: TestClient, tmp_path, monkeypatch) -> None:
    history_dir = tmp_path / "histories"
    replay_dir = tmp_path / "replays"
    report_dir = tmp_path / "reports"
    screenshot_dir = tmp_path / "screenshots"
    monkeypatch.setattr("smart_automator.server.history_store.HISTORY_DIR", history_dir)
    monkeypatch.setattr("smart_automator.server.replay_store.REPLAY_DIR", replay_dir)
    monkeypatch.setattr("smart_automator.server.app.REPORT_DIR", report_dir)
    monkeypatch.setattr("smart_automator.server.app.SCREENSHOT_DIR", screenshot_dir)

    run_id = "artifact-purge-run"
    save_run_history(run_id, AgentStepHistory())
    save_run_replay(run_id, [], "print('replay')")
    report_file = report_dir / f"{run_id}.html"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file.write_text("<html></html>", encoding="utf-8")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    (screenshot_dir / f"{run_id[:8]}_step_1.png").write_bytes(b"png")

    run = RunState(
        run_id=run_id,
        task="Artifact test",
        headless=True,
        max_steps=5,
        success_criteria="ok",
    )
    run.status = "fail"
    run.finished_at = time.time()
    run.report_path = str(report_file)
    add_run(run)

    res = client.delete(f"/api/runs/{run_id}?purge=true")
    assert res.status_code == 200
    assert not history_path(run_id).is_file()
    assert not replay_json_path(run_id).is_file()
    assert not report_file.is_file()
    assert not (screenshot_dir / f"{run_id[:8]}_step_1.png").is_file()


def test_delete_without_purge_leaves_finished_run(client: TestClient) -> None:
    run = RunState(
        run_id="keep-finished-run",
        task="Keep me",
        headless=True,
        max_steps=5,
        success_criteria="ok",
    )
    run.status = "pass"
    run.finished_at = time.time()
    add_run(run)

    res = client.delete("/api/runs/keep-finished-run")
    assert res.status_code == 200
    assert get_run("keep-finished-run") is not None

    client.delete("/api/runs/keep-finished-run?purge=true")
