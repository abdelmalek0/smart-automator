"""Tests for latest successful trained replay per project test."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from smart_automator.agent.history import AgentStepHistory, AgentStepRecord
from smart_automator.agent.context import ActionResult
from smart_automator.server import replay_store
from smart_automator.server.run_store import save_run_record
from smart_automator.server.run_state import RunState, add_run
from smart_automator.server.runner import _set_terminal_status, run_automation
from smart_automator.storage.websites import WebsiteStore


def _create_website_with_task(client: TestClient) -> tuple[dict, dict]:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    task = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={
            "name": "Smoke",
            "task": "Open home page",
            "success_criteria": "Home page loads",
        },
    ).json()
    return website, task


def test_website_task_round_trips_trained_replay_fields(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    store = WebsiteStore(user_id)
    store.update_task(website["id"], task["id"], last_trained_run_id="trained-run")
    replay_store.save_run_replay(
        "trained-run",
        [{"index": 1, "action": "wait", "args": {"seconds": 1}}],
        "# script",
    )
    trained_run = RunState(
        run_id="trained-run",
        user_id=user_id,
        task=task["task"],
        headless=True,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
    )
    trained_run.status = "pass"
    trained_run.finished_at = time.time()
    add_run(trained_run)
    trained_run.persist()

    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data["last_trained_run_id"] == "trained-run"
    assert task_data["has_trained_replay"] is True


def test_failed_training_replay_does_not_count_as_trained(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    failed_run_id = "failed-trained-run"
    WebsiteStore(user_id).update_task(
        website["id"],
        task["id"],
        last_trained_run_id=failed_run_id,
    )
    replay_store.save_run_replay(
        failed_run_id,
        [{"index": 1, "action": "wait", "args": {"seconds": 1}}],
        "# script",
    )
    failed_run = RunState(
        run_id=failed_run_id,
        user_id=user_id,
        task=task["task"],
        headless=True,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
    )
    failed_run.status = "fail"
    failed_run.finished_at = time.time()
    add_run(failed_run)
    failed_run.persist()

    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data["last_trained_run_id"] == failed_run_id
    assert task_data["has_trained_replay"] is False


def test_start_run_with_website_task_id(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    res = client.post(
        "/api/runs",
        json={
            "task": task["task"],
            "success_criteria": task["success_criteria"],
            "website_id": website["id"],
            "website_task_id": task["id"],
            "headless": True,
            "max_steps": 5,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["website_id"] == website["id"]
    assert body["website_task_id"] == task["id"]


def test_start_run_rejects_unknown_website_task(client: TestClient) -> None:
    website, _task = _create_website_with_task(client)
    res = client.post(
        "/api/runs",
        json={
            "task": "Do something",
            "success_criteria": "Done",
            "website_id": website["id"],
            "website_task_id": "missing-task-id",
            "headless": True,
            "max_steps": 5,
        },
    )
    assert res.status_code == 404
    assert "Website task not found" in res.json()["detail"]


def test_start_automatic_from_task_last_trained_run(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    source_run_id = "source-trained-run"
    source = RunState(
        run_id=source_run_id,
        user_id=user_id,
        task=task["task"],
        headless=True,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
    )
    source.status = "pass"
    source.finished_at = time.time()
    add_run(source)
    source.persist()
    replay_store.save_run_replay(
        source_run_id,
        [{"index": 1, "action": "wait", "args": {"seconds": 1}}],
        "# script",
    )
    WebsiteStore(user_id).update_task(
        website["id"],
        task["id"],
        last_trained_run_id=source_run_id,
    )

    res = client.post(
        "/api/runs",
        json={
            "task": task["task"],
            "success_criteria": task["success_criteria"],
            "website_id": website["id"],
            "website_task_id": task["id"],
            "source_run_id": source_run_id,
            "use_replay_script": True,
            "headless": True,
            "max_steps": 5,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["source_run_id"] == source_run_id
    assert body["use_replay_script"] is True


def _human_click_history() -> AgentStepHistory:
    element = type(
        "El",
        (),
        {
            "to_dict": lambda self: {
                "tagName": "button",
                "xpath": "html/body/button",
                "attributes": {"type": "button"},
                "cssSelector": "button[type='button']",
            }
        },
    )()
    return AgentStepHistory(
        history=[
            AgentStepRecord(
                model_output='{"action":[{"click_element":{"xpath":"html/body/button"}}]}',
                result=[
                    ActionResult(
                        success=True,
                        extracted_content="Clicked",
                        action_name="click_element",
                        interacted_element=element,
                    )
                ],
                state=type(
                    "State",
                    (),
                    {
                        "url": "https://example.com",
                        "title": "Example",
                        "to_dict": lambda self: {
                            "url": "https://example.com",
                            "title": "Example",
                            "tabs": [],
                            "interactedElements": [],
                        },
                    },
                )(),
                metadata={"source": "agent"},
            )
        ]
    )


def test_pass_training_updates_task_pointer(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="pass-training-run",
        user_id=user_id,
        task=task["task"],
        headless=True,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
    )
    add_run(run)

    executor = MagicMock()
    executor.context.history = _human_click_history()
    executor.flush_token_usage = MagicMock()
    executor.cleanup = MagicMock()

    def mark_pass_and_execute() -> bool:
        _set_terminal_status(run, "pass", "Criteria met.")
        return True

    executor.execute = MagicMock(side_effect=mark_pass_and_execute)

    with patch("smart_automator.server.runner.config_for_run"), patch(
        "smart_automator.server.runner.create_llm"
    ), patch("smart_automator.server.runner.BrowserContext") as browser_context_cls, patch(
        "smart_automator.server.runner.Executor", return_value=executor
    ), patch("smart_automator.server.runner._generate_report"):
        browser_context_cls.return_value.launch = MagicMock()
        browser_context_cls.return_value.new_page = MagicMock()
        browser_context_cls.return_value.close = MagicMock()
        run_automation(run)
        save_run_record(
            user_id,
            run.run_id,
            {
                "run_id": run.run_id,
                "user_id": user_id,
                "status": "pass",
                "use_replay_script": False,
            },
        )

    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data["last_trained_run_id"] == "pass-training-run"
    assert task_data["has_trained_replay"] is True
    assert replay_store.load_run_replay(run.run_id) is not None


def test_failed_training_does_not_save_replay(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="failed-training-run",
        user_id=user_id,
        task=task["task"],
        headless=True,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
    )
    add_run(run)

    executor = MagicMock()
    executor.context.history = _human_click_history()
    executor.flush_token_usage = MagicMock()
    executor.cleanup = MagicMock()

    def mark_fail_and_execute() -> bool:
        _set_terminal_status(run, "fail", "Criteria not met.")
        return True

    executor.execute = MagicMock(side_effect=mark_fail_and_execute)

    with patch("smart_automator.server.runner.config_for_run"), patch(
        "smart_automator.server.runner.create_llm"
    ), patch("smart_automator.server.runner.BrowserContext") as browser_context_cls, patch(
        "smart_automator.server.runner.Executor", return_value=executor
    ), patch("smart_automator.server.runner._generate_report"):
        browser_context_cls.return_value.launch = MagicMock()
        browser_context_cls.return_value.new_page = MagicMock()
        browser_context_cls.return_value.close = MagicMock()
        run_automation(run)

    assert replay_store.load_run_replay(run.run_id) is None
    store = WebsiteStore(user_id)
    task_obj = store.get_website(website["id"]).tasks[0]
    assert task_obj.last_trained_run_id is None


def test_purge_clears_last_trained_pointer(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run_id = "purge-target-run"
    source = RunState(
        run_id=run_id,
        user_id=user_id,
        task=task["task"],
        headless=True,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
    )
    source.status = "pass"
    source.finished_at = time.time()
    add_run(source)
    source.persist()
    replay_store.save_run_replay(
        run_id,
        [{"index": 1, "action": "wait", "args": {"seconds": 1}}],
        "# script",
    )
    WebsiteStore(user_id).update_task(
        website["id"],
        task["id"],
        last_trained_run_id=run_id,
    )

    res = client.delete(f"/api/runs/{run_id}?purge=true")
    assert res.status_code == 200

    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data.get("last_trained_run_id") is None
    assert task_data["has_trained_replay"] is False
