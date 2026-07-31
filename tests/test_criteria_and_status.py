"""Tests for success criteria, run status model, and replay re-run API."""

from __future__ import annotations

import time
import unittest

import pytest
from fastapi.testclient import TestClient

from smart_automator.agent.history import AgentStepHistory
from smart_automator.agents.output_schemas import validate_criteria_output
from smart_automator.reporting.builder import build_report_data
from smart_automator.reporting.html_report import render_html_report
from smart_automator.server.app import app
from smart_automator.server.history_store import load_run_history, save_run_history
from smart_automator.server.run_state import RunState, add_run
from smart_automator.server.step_mapper import compose_agent_task, compose_task


def test_start_run_requires_success_criteria(client: TestClient) -> None:
    res = client.post("/api/runs", json={"task": "Do something"})
    assert res.status_code == 422


def test_start_run_includes_new_fields(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "name": "Checkout smoke",
            "task": "Add item and checkout",
            "success_criteria": "Order confirmation is visible",
            "headless": True,
            "max_steps": 25,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Checkout smoke"
    assert body["success_criteria"] == "Order confirmation is visible"
    assert body["source_run_id"] is None


def test_start_run_rejects_missing_source_run(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "task": "Replay test",
            "success_criteria": "Page loads",
            "source_run_id": "00000000-0000-0000-0000-000000000000",
            "use_replay_script": False,
        },
    )
    assert res.status_code == 404
    assert "Source run not found" in res.json()["detail"]


def test_start_run_training_rerun_accepts_lineage(client: TestClient) -> None:
    source_res = client.post(
        "/api/runs",
        json={
            "task": "Original task",
            "success_criteria": "Page loads",
            "headless": True,
            "max_steps": 5,
        },
    )
    assert source_res.status_code == 201
    source_run_id = source_res.json()["run_id"]

    res = client.post(
        "/api/runs",
        json={
            "task": "Original task",
            "success_criteria": "Page loads",
            "source_run_id": source_run_id,
            "use_replay_script": False,
            "headless": True,
            "max_steps": 5,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["source_run_id"] == source_run_id
    assert body["use_replay_script"] is False


def test_start_run_rejects_script_replay_without_source(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "task": "Replay test",
            "success_criteria": "Page loads",
            "use_replay_script": True,
        },
    )
    assert res.status_code == 400
    assert "source_run_id is required" in res.json()["detail"]


def test_start_run_rejects_missing_replay_script(client: TestClient) -> None:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    source_run_id = "00000000-0000-0000-0000-000000000000"
    source = RunState(
        run_id=source_run_id,
        user_id=user_id,
        task="Source",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    source.status = "pass"
    source.finished_at = time.time()
    add_run(source)
    source.persist()

    res = client.post(
        "/api/runs",
        json={
            "task": "Replay test",
            "success_criteria": "Page loads",
            "source_run_id": source_run_id,
            "use_replay_script": True,
        },
    )
    assert res.status_code == 400
    assert "Replay script not found" in res.json()["detail"]


def test_start_run_script_replay_includes_fields(client: TestClient, tmp_path, monkeypatch) -> None:
    from smart_automator.server import replay_store

    monkeypatch.setattr(replay_store, "REPLAY_DIR", tmp_path)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    source = RunState(
        run_id="source-run",
        user_id=user_id,
        task="Source",
        headless=True,
        max_steps=5,
        success_criteria="Done",
    )
    source.status = "pass"
    source.finished_at = time.time()
    add_run(source)
    source.persist()
    replay_store.save_run_replay(
        "source-run",
        [{"index": 1, "action": "wait", "args": {"seconds": 1}}],
        "# script",
    )

    res = client.post(
        "/api/runs",
        json={
            "task": "Replay test",
            "success_criteria": "Page loads",
            "source_run_id": "source-run",
            "use_replay_script": True,
            "headless": True,
            "max_steps": 5,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["source_run_id"] == "source-run"
    assert body["use_replay_script"] is True


def test_website_task_requires_success_criteria(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={"task": "Login"},
    )
    assert res.status_code == 422


def test_website_task_round_trips_new_fields(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={
            "name": "Login test",
            "task": "Log in with demo credentials",
            "success_criteria": "Dashboard is visible",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Login test"
    assert body["success_criteria"] == "Dashboard is visible"


class TestComposeTask(unittest.TestCase):
    def test_includes_success_criteria_and_test_name(self):
        composed = compose_task(
            "Add item to cart",
            name="Shop",
            url="https://shop.example.com",
            context_prompt="Use demo account",
            success_criteria="Cart shows one item",
            test_name="Cart smoke",
        )
        self.assertIn("Test: Cart smoke", composed)
        self.assertIn("Success criteria: Cart shows one item", composed)
        self.assertIn("Task: Add item to cart", composed)

    def test_agent_task_excludes_success_criteria(self):
        agent_task = compose_agent_task(
            "Add item to cart",
            name="Shop",
            url="https://shop.example.com",
            context_prompt="Use demo account",
            test_name="Cart smoke",
        )
        self.assertIn("Task: Add item to cart", agent_task)
        self.assertNotIn("Success criteria:", agent_task)


class TestCriteriaOutput(unittest.TestCase):
    def test_validate_criteria_output_coerces_passed(self):
        result = validate_criteria_output(
            {"passed": "true", "evidence": "Saw confirmation", "reason": "Criteria met"}
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence"], "Saw confirmation")


class TestHistoryStore(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        import tempfile
        from pathlib import Path
        from smart_automator.server import history_store

        history = AgentStepHistory(history=[])
        with tempfile.TemporaryDirectory() as tmp:
            original = history_store.HISTORY_DIR
            history_store.HISTORY_DIR = Path(tmp)
            try:
                save_run_history("run-abc", history)
                loaded = load_run_history("run-abc")
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.history, [])
            finally:
                history_store.HISTORY_DIR = original


class TestReportCriteriaFields(unittest.TestCase):
    def test_build_report_data_includes_criteria(self):
        run = RunState(
            run_id="run-1",
            task="Checkout",
            headless=True,
            max_steps=10,
            success_criteria="Confirmation page visible",
            name="Checkout smoke",
            user_id="test-user",
        )
        run.status = "pass"
        run.criteria_verdict = {
            "passed": True,
            "reason": "Confirmation heading found",
            "evidence": "Thank you for your order",
        }
        data = build_report_data(run, AgentStepHistory())
        self.assertEqual(data["success_criteria"], "Confirmation page visible")
        self.assertEqual(data["name"], "Checkout smoke")
        self.assertTrue(data["criteria_verdict"]["passed"])

        html = render_html_report(data)
        self.assertIn("Success criteria:", html)
        self.assertIn("Criteria verdict:", html)


if __name__ == "__main__":
    unittest.main()
