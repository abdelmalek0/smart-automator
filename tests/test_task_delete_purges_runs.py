"""Deleting a test or project purges related runs, unless any are still live."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from smart_automator.server.history_store import history_path, save_run_history
from smart_automator.server.replay_store import replay_json_path, save_run_replay
from smart_automator.server.run_state import RunState, add_run, get_run
from smart_automator.agent.history import AgentStepHistory


def _create_project_with_tasks(client: TestClient, *, extra_task: bool = False) -> tuple[str, str, str | None]:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    first = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={"task": "First test", "success_criteria": "ok"},
    ).json()
    second_id = None
    if extra_task:
        second = client.post(
            f"/api/websites/{website['id']}/tasks",
            json={"task": "Second test", "success_criteria": "ok"},
        ).json()
        second_id = second["id"]
    return website["id"], first["id"], second_id


def _finished_run(
    *,
    user_id: str,
    run_id: str,
    website_id: str,
    website_task_id: str,
    status: str = "pass",
) -> RunState:
    run = RunState(
        run_id=run_id,
        task="Task",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website_id,
        website_task_id=website_task_id,
    )
    run.status = status
    run.finished_at = time.time()
    add_run(run)
    run.persist()
    return run


def test_delete_task_purges_matching_runs_and_artifacts(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    history_dir = tmp_path / "histories"
    replay_dir = tmp_path / "replays"
    report_dir = tmp_path / "reports"
    screenshot_dir = tmp_path / "screenshots"
    monkeypatch.setattr("smart_automator.server.history_store.HISTORY_DIR", history_dir)
    monkeypatch.setattr("smart_automator.server.replay_store.REPLAY_DIR", replay_dir)
    monkeypatch.setattr("smart_automator.server.app.REPORT_DIR", report_dir)
    monkeypatch.setattr("smart_automator.server.app.SCREENSHOT_DIR", screenshot_dir)

    website_id, task_id, other_task_id = _create_project_with_tasks(client, extra_task=True)
    user_id = client.get("/api/auth/me").json()["user"]["id"]

    run_id = "task-purge-run"
    save_run_history(run_id, AgentStepHistory())
    save_run_replay(run_id, [], "print('replay')")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"{run_id}.html"
    report_file.write_text("<html></html>", encoding="utf-8")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    (screenshot_dir / f"{run_id[:8]}_step_1.png").write_bytes(b"png")

    matching = _finished_run(
        user_id=user_id,
        run_id=run_id,
        website_id=website_id,
        website_task_id=task_id,
        status="fail",
    )
    matching.report_path = str(report_file)
    matching.persist()

    other = _finished_run(
        user_id=user_id,
        run_id="other-task-run",
        website_id=website_id,
        website_task_id=other_task_id or "",
        status="pass",
    )

    res = client.delete(f"/api/websites/{website_id}/tasks/{task_id}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    tasks = client.get(f"/api/websites/{website_id}").json()["tasks"]
    assert all(task["id"] != task_id for task in tasks)

    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert run_id not in listed
    assert other.run_id in listed
    assert get_run(run_id) is None

    assert not history_path(run_id).is_file()
    assert not replay_json_path(run_id).is_file()
    assert not report_file.is_file()
    assert not (screenshot_dir / f"{run_id[:8]}_step_1.png").is_file()


def test_delete_task_blocked_when_run_is_active(client: TestClient) -> None:
    website_id, task_id, _ = _create_project_with_tasks(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="live-task-run",
        task="Live",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website_id,
        website_task_id=task_id,
    )
    run.status = "running"
    add_run(run)
    run.persist()

    res = client.delete(f"/api/websites/{website_id}/tasks/{task_id}")
    assert res.status_code == 409
    assert res.json()["detail"] == "Cancel the run before deleting it"

    tasks = client.get(f"/api/websites/{website_id}").json()["tasks"]
    assert any(task["id"] == task_id for task in tasks)
    assert get_run("live-task-run") is not None
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "live-task-run" in listed


def test_delete_other_task_while_one_run_is_live(client: TestClient) -> None:
    website_id, live_task_id, other_task_id = _create_project_with_tasks(client, extra_task=True)
    assert other_task_id is not None
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    live = RunState(
        run_id="keep-live-run",
        task="Live",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website_id,
        website_task_id=live_task_id,
    )
    live.status = "running"
    add_run(live)
    live.persist()
    _finished_run(
        user_id=user_id,
        run_id="other-history-run",
        website_id=website_id,
        website_task_id=other_task_id,
    )

    res = client.delete(f"/api/websites/{website_id}/tasks/{other_task_id}")
    assert res.status_code == 200
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "other-history-run" not in listed
    assert "keep-live-run" in listed
    assert get_run("keep-live-run") is not None
    assert get_run("other-history-run") is None
    tasks = client.get(f"/api/websites/{website_id}").json()["tasks"]
    assert any(task["id"] == live_task_id for task in tasks)
    assert all(task["id"] != other_task_id for task in tasks)


def test_delete_task_purges_runs_matched_only_by_task_id(client: TestClient) -> None:
    website_id, task_id, live_task_id = _create_project_with_tasks(client, extra_task=True)
    assert live_task_id is not None
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    live = RunState(
        run_id="unrelated-live-run",
        task="Live",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website_id,
        website_task_id=live_task_id,
    )
    live.status = "running"
    add_run(live)
    live.persist()

    orphan = RunState(
        run_id="task-id-only-run",
        task="First test",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_task_id=task_id,
    )
    orphan.status = "pass"
    orphan.finished_at = time.time()
    add_run(orphan)
    orphan.persist()

    res = client.delete(f"/api/websites/{website_id}/tasks/{task_id}")
    assert res.status_code == 200
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "task-id-only-run" not in listed
    assert "unrelated-live-run" in listed


def test_delete_task_purges_legacy_runs_without_task_id(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    task = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={"name": "Checkout", "task": "Buy the thing", "success_criteria": "ok"},
    ).json()
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="legacy-named-run",
        task="Buy the thing",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website["id"],
        name="Checkout",
    )
    run.status = "pass"
    run.finished_at = time.time()
    add_run(run)
    run.persist()

    res = client.delete(f"/api/websites/{website['id']}/tasks/{task['id']}")
    assert res.status_code == 200
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "legacy-named-run" not in listed


def test_delete_task_allows_cancelled_runs(client: TestClient) -> None:
    website_id, task_id, _ = _create_project_with_tasks(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    _finished_run(
        user_id=user_id,
        run_id="cancelled-task-run",
        website_id=website_id,
        website_task_id=task_id,
        status="cancelled",
    )

    res = client.delete(f"/api/websites/{website_id}/tasks/{task_id}")
    assert res.status_code == 200
    assert get_run("cancelled-task-run") is None


def test_delete_project_blocked_when_run_is_active(client: TestClient) -> None:
    website_id, task_id, _ = _create_project_with_tasks(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="live-project-run",
        task="Live",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website_id,
        website_task_id=task_id,
    )
    run.status = "pending"
    add_run(run)
    run.persist()

    res = client.delete(f"/api/websites/{website_id}")
    assert res.status_code == 409
    assert res.json()["detail"] == "Cancel the run before deleting it"
    assert client.get(f"/api/websites/{website_id}").status_code == 200
    assert get_run("live-project-run") is not None


def test_delete_project_purges_all_project_runs(client: TestClient) -> None:
    website_id, task_id, other_task_id = _create_project_with_tasks(client, extra_task=True)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    _finished_run(
        user_id=user_id,
        run_id="proj-run-a",
        website_id=website_id,
        website_task_id=task_id,
    )
    _finished_run(
        user_id=user_id,
        run_id="proj-run-b",
        website_id=website_id,
        website_task_id=other_task_id or "",
        status="fail",
    )
    leftover = _finished_run(
        user_id=user_id,
        run_id="other-project-run",
        website_id="unrelated-website",
        website_task_id="unrelated-task",
    )

    res = client.delete(f"/api/websites/{website_id}")
    assert res.status_code == 200
    assert client.get(f"/api/websites/{website_id}").status_code == 404

    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "proj-run-a" not in listed
    assert "proj-run-b" not in listed
    assert leftover.run_id in listed


def test_delete_other_project_while_one_project_run_is_live(client: TestClient) -> None:
    live_website_id, live_task_id, _ = _create_project_with_tasks(client)
    other_website_id, other_task_id, extra_task_id = _create_project_with_tasks(
        client, extra_task=True
    )
    assert extra_task_id is not None
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    live = RunState(
        run_id="keep-other-project-live",
        task="Live",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=live_website_id,
        website_task_id=live_task_id,
    )
    live.status = "running"
    add_run(live)
    live.persist()
    _finished_run(
        user_id=user_id,
        run_id="delete-me-a",
        website_id=other_website_id,
        website_task_id=other_task_id,
    )
    _finished_run(
        user_id=user_id,
        run_id="delete-me-b",
        website_id=other_website_id,
        website_task_id=extra_task_id,
        status="cancelled",
    )

    res = client.delete(f"/api/websites/{other_website_id}")
    assert res.status_code == 200
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "delete-me-a" not in listed
    assert "delete-me-b" not in listed
    assert "keep-other-project-live" in listed
    assert client.get(f"/api/websites/{live_website_id}").status_code == 200
    assert client.get(f"/api/websites/{other_website_id}").status_code == 404


def test_delete_project_purges_legacy_named_runs(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Shop"}).json()
    client.post(
        f"/api/websites/{website['id']}/tasks",
        json={"name": "Checkout", "task": "Buy the thing", "success_criteria": "ok"},
    )
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="project-legacy-named-run",
        task="Buy the thing",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=website["id"],
        name="Checkout",
    )
    run.status = "pass"
    run.finished_at = time.time()
    add_run(run)
    run.persist()

    res = client.delete(f"/api/websites/{website['id']}")
    assert res.status_code == 200
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "project-legacy-named-run" not in listed


def test_delete_project_purges_artifacts(client: TestClient, tmp_path, monkeypatch) -> None:
    history_dir = tmp_path / "histories"
    replay_dir = tmp_path / "replays"
    report_dir = tmp_path / "reports"
    screenshot_dir = tmp_path / "screenshots"
    monkeypatch.setattr("smart_automator.server.history_store.HISTORY_DIR", history_dir)
    monkeypatch.setattr("smart_automator.server.replay_store.REPLAY_DIR", replay_dir)
    monkeypatch.setattr("smart_automator.server.app.REPORT_DIR", report_dir)
    monkeypatch.setattr("smart_automator.server.app.SCREENSHOT_DIR", screenshot_dir)

    website_id, task_id, _ = _create_project_with_tasks(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run_id = "project-artifact-run"
    save_run_history(run_id, AgentStepHistory())
    save_run_replay(run_id, [], "print('replay')")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"{run_id}.html"
    report_file.write_text("<html></html>", encoding="utf-8")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    (screenshot_dir / f"{run_id[:8]}_step_1.png").write_bytes(b"png")
    matching = _finished_run(
        user_id=user_id,
        run_id=run_id,
        website_id=website_id,
        website_task_id=task_id,
    )
    matching.report_path = str(report_file)
    matching.persist()

    res = client.delete(f"/api/websites/{website_id}")
    assert res.status_code == 200
    assert get_run(run_id) is None
    assert not history_path(run_id).is_file()
    assert not replay_json_path(run_id).is_file()
    assert not report_file.is_file()
    assert not (screenshot_dir / f"{run_id[:8]}_step_1.png").is_file()


def test_delete_project_purges_runs_matched_only_by_task_id(client: TestClient) -> None:
    website_id, task_id, _ = _create_project_with_tasks(client)
    other_website_id, other_task_id, _ = _create_project_with_tasks(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    live = RunState(
        run_id="other-project-live",
        task="Live",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_id=other_website_id,
        website_task_id=other_task_id,
    )
    live.status = "running"
    add_run(live)
    live.persist()

    orphan = RunState(
        run_id="project-task-id-only-run",
        task="First test",
        headless=True,
        max_steps=5,
        success_criteria="ok",
        user_id=user_id,
        website_task_id=task_id,
    )
    orphan.status = "pass"
    orphan.finished_at = time.time()
    add_run(orphan)
    orphan.persist()

    res = client.delete(f"/api/websites/{website_id}")
    assert res.status_code == 200
    listed = {item["run_id"] for item in client.get("/api/runs").json()}
    assert "project-task-id-only-run" not in listed
    assert "other-project-live" in listed
    assert client.get(f"/api/websites/{other_website_id}").status_code == 200

