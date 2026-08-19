"""Tests for manual demonstration mode."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from smart_automator.agent.context import ActionResult
from smart_automator.agent.history import AgentStepHistory, AgentStepRecord
from smart_automator.agents.errors import RequestCancelledError
from smart_automator.agents.output_schemas import validate_task_extractor_output
from smart_automator.agents.task_extractor import TASK_EXTRACTOR_SYSTEM_PROMPT, TaskExtractorAgent
from smart_automator.server import replay_store
from smart_automator.server.run_store import save_run_record
from smart_automator.server.run_state import RunState, add_run
from smart_automator.server.runner import run_automation


def _create_website_with_task(client: TestClient) -> tuple[dict, dict]:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    task = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={
            "name": "Smoke",
            "task": "Human demonstration",
            "success_criteria": "Home page loads",
        },
    ).json()
    return website, task


def _click_history() -> AgentStepHistory:
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
                        extracted_content="Clicked Checkout",
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
                metadata={"source": "human"},
            )
        ]
    )


def test_start_manual_allows_empty_task(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "run_mode": "manual",
            "success_criteria": "Confirmation is visible",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["run_mode"] == "manual"
    assert body["use_replay_script"] is False
    assert body["task"] == "Human demonstration"
    assert body["success_criteria"] == "Confirmation is visible"


def test_start_manual_rejects_headless(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "run_mode": "manual",
            "success_criteria": "Done",
            "headless": True,
        },
    )
    assert res.status_code == 400
    assert "headless" in res.json()["detail"].lower()


def test_start_manual_does_not_use_replay_script(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "run_mode": "manual",
            "success_criteria": "Done",
            "use_replay_script": True,
            "source_run_id": "anything",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["run_mode"] == "manual"
    assert body["use_replay_script"] is False
    assert body["source_run_id"] is None


def test_start_run_still_requires_task_for_training(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={"run_mode": "training", "success_criteria": "Done"},
    )
    assert res.status_code == 400
    assert "Task is required" in res.json()["detail"]


def test_finish_manual_rejects_training_run(client: TestClient) -> None:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="training-run",
        user_id=user_id,
        task="Do it",
        headless=False,
        max_steps=5,
        success_criteria="Done",
        run_mode="training",
    )
    run.status = "running"
    run.executor = MagicMock()
    add_run(run)
    res = client.post(f"/api/runs/{run.run_id}/finish-manual")
    assert res.status_code == 400
    assert "manual" in res.json()["detail"].lower()


def test_finish_manual_queues_command(client: TestClient, monkeypatch) -> None:
    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("smart_automator.server.app.asyncio.to_thread", immediate_to_thread)

    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="manual-run",
        user_id=user_id,
        task="Human demonstration",
        headless=False,
        max_steps=5,
        success_criteria="Done",
        run_mode="manual",
    )
    run.status = "awaiting_human"
    executor = MagicMock()
    executor.submit_hitl_command.return_value = (True, None)
    run.executor = executor
    add_run(run)

    res = client.post(f"/api/runs/{run.run_id}/finish-manual")
    assert res.status_code == 200, res.text
    executor.submit_hitl_command.assert_called_once_with("finish_manual", wait=False)


def test_return_control_rejected_for_manual(client: TestClient) -> None:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="manual-return",
        user_id=user_id,
        task="Human demonstration",
        headless=False,
        max_steps=5,
        success_criteria="Done",
        run_mode="manual",
    )
    run.status = "running"
    run.executor = MagicMock()
    add_run(run)
    res = client.post(f"/api/runs/{run.run_id}/return-control")
    assert res.status_code == 400


@contextmanager
def _patch_run_automation(executor: MagicMock):
    llm = MagicMock()
    with patch("smart_automator.server.runner.config_for_run"), patch(
        "smart_automator.server.runner.create_role_llms",
        return_value=(llm, llm),
    ), patch("smart_automator.server.runner.local_browser_mode_enabled", return_value=True), patch(
        "smart_automator.server.runner.BrowserContext"
    ) as browser_context_cls, patch(
        "smart_automator.server.runner.Executor", return_value=executor
    ), patch("smart_automator.server.runner._generate_report"), patch(
        "smart_automator.server.runner.CriteriaCheckerAgent"
    ) as criteria_cls:
        browser_context_cls.return_value.launch = MagicMock()
        browser_context_cls.return_value.new_page = MagicMock()
        browser_context_cls.return_value.close = MagicMock()
        yield criteria_cls


def test_manual_done_saves_replay_and_trains_without_criteria(
    client: TestClient,
) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="manual-pass-run",
        user_id=user_id,
        task="Human demonstration",
        headless=False,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
        run_mode="manual",
    )
    add_run(run)

    executor = MagicMock()
    executor.context.history = _click_history()
    executor.context.browser_context.get_current_page.return_value.url.return_value = (
        "https://example.com/done"
    )
    executor.context.browser_context.get_current_page.return_value.title.return_value = "Done"
    executor.flush_token_usage = MagicMock()
    executor.cleanup = MagicMock()
    executor.execute_manual = MagicMock(return_value="manual_complete")
    executor.hitl.flush_recorded_to_history = MagicMock()
    executor.hitl._session_start_url = "https://example.com"
    executor.hitl._session_start_title = "Home"

    with _patch_run_automation(executor) as criteria_cls, patch(
        "smart_automator.server.runner.TaskExtractorAgent"
    ) as extractor_cls:
        extractor_cls.action_lines_from_history.return_value = ["Clicked Checkout"]
        extractor_cls.return_value.extract.return_value = {
            "task": "1. Click Checkout",
            "name": "Checkout flow",
        }
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

    criteria_cls.assert_not_called()
    assert run.status == "pass"
    assert run.task == "1. Click Checkout"
    assert run.name == "Checkout flow"
    assert replay_store.load_run_replay(run.run_id) is not None

    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data["task"] == "1. Click Checkout"
    assert task_data["last_trained_run_id"] == "manual-pass-run"
    assert task_data["has_trained_replay"] is True


def test_manual_done_with_zero_actions_fails(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="manual-empty-run",
        user_id=user_id,
        task="Human demonstration",
        headless=False,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
        run_mode="manual",
    )
    add_run(run)

    executor = MagicMock()
    executor.context.history = AgentStepHistory(history=[])
    executor.flush_token_usage = MagicMock()
    executor.cleanup = MagicMock()
    executor.execute_manual = MagicMock(return_value=None)
    executor.hitl.flush_recorded_to_history = MagicMock()

    with _patch_run_automation(executor) as criteria_cls:
        run_automation(run)

    criteria_cls.assert_not_called()
    assert run.status == "fail"
    assert replay_store.load_run_replay(run.run_id) is None
    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data.get("last_trained_run_id") in (None, "")
    assert task_data["has_trained_replay"] is False


def test_manual_cancel_does_not_train(client: TestClient) -> None:
    website, task = _create_website_with_task(client)
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="manual-cancel-run",
        user_id=user_id,
        task="Human demonstration",
        headless=False,
        max_steps=5,
        success_criteria=task["success_criteria"],
        website_id=website["id"],
        website_task_id=task["id"],
        run_mode="manual",
    )
    add_run(run)

    executor = MagicMock()
    executor.context.history = _click_history()
    executor.flush_token_usage = MagicMock()
    executor.cleanup = MagicMock()
    executor.execute_manual = MagicMock(side_effect=RequestCancelledError("Request cancelled"))

    with _patch_run_automation(executor):
        run_automation(run)

    assert run.status == "cancelled"
    assert replay_store.load_run_replay(run.run_id) is None
    refreshed = client.get(f"/api/websites/{website['id']}").json()
    task_data = next(item for item in refreshed["tasks"] if item["id"] == task["id"])
    assert task_data["has_trained_replay"] is False


def test_validate_task_extractor_output() -> None:
    result = validate_task_extractor_output({"task": " 1. Click ", "name": " Login "})
    assert result["task"] == "1. Click"
    assert result["name"] == "Login"


def test_task_from_action_lines() -> None:
    assert TaskExtractorAgent.task_from_action_lines([]) == "Complete the demonstrated browser flow."
    assert TaskExtractorAgent.task_from_action_lines(["Click A", "Type B"]) == "1. Click A\n2. Type B"
    assert TaskExtractorAgent.task_from_action_lines(
        ["On page: https://example.com", "Click A"]
    ) == "1. Click A"


def test_action_lines_from_history() -> None:
    lines = TaskExtractorAgent.action_lines_from_history(_click_history())
    assert lines
    joined = "\n".join(lines)
    assert "Click Checkout" in joined
    assert "xpath" not in joined.lower()


def _pin_history() -> AgentStepHistory:
    return AgentStepHistory(
        history=[
            AgentStepRecord(
                model_output='{"action":[{"input_text":{"text":"4821","xpath":"html/body/input"}}]}',
                result=[
                    ActionResult(
                        success=True,
                        extracted_content="Human entered '4821' in the password field labeled 'PIN'",
                        action_name="input_text",
                    )
                ],
                state=type(
                    "State",
                    (),
                    {
                        "url": "https://example.com/pin",
                        "title": "Unlock",
                        "to_dict": lambda self: {
                            "url": "https://example.com/pin",
                            "title": "Unlock",
                            "tabs": [],
                            "interactedElements": [],
                        },
                    },
                )(),
                metadata={"source": "human"},
            )
        ]
    )


def test_action_lines_include_pin_and_omit_xpath() -> None:
    lines = TaskExtractorAgent.action_lines_from_history(_pin_history())
    joined = "\n".join(lines)
    assert "4821" in joined
    assert "PIN" in joined
    assert "xpath" not in joined.lower()
    assert "[redacted]" not in joined
    task = TaskExtractorAgent.task_from_action_lines(lines)
    assert "4821" in task
    assert task.startswith("1. Type ")
    assert "On page:" not in task


def test_extractor_prompt_is_name_only() -> None:
    prompt = TASK_EXTRACTOR_SYSTEM_PROMPT
    assert "name" in prompt.lower()
    assert "xpath" in prompt.lower()
    assert "Do not write steps" in prompt


def test_extract_uses_recorded_step_descriptions() -> None:
    agent = TaskExtractorAgent(MagicMock())
    lines = [
        "Human clicked ItemOne",
        "Human entered '4821' in FieldA",
        "Human clicked ItemTwo",
    ]
    with patch.object(
        agent,
        "get_json_response",
        return_value={"task": "1. ...\n2. ...", "name": "Pay"},
    ) as llm:
        result = agent.extract(action_lines=lines)
    llm.assert_called_once()
    assert result["name"] == "Pay"
    assert result["task"] == (
        "1. Click ItemOne\n"
        "2. Type '4821' in FieldA\n"
        "3. Click ItemTwo"
    )


def test_extract_keeps_existing_name_and_skips_llm() -> None:
    agent = TaskExtractorAgent(MagicMock())
    with patch.object(agent, "get_json_response") as llm:
        result = agent.extract(
            action_lines=["Human clicked ItemOne"],
            existing_name="Checkout smoke",
        )
    llm.assert_not_called()
    assert result["name"] == "Checkout smoke"
    assert result["task"] == "1. Click ItemOne"
    assert result["extractor_llm_ms"] == 0


def test_action_lines_use_extracted_content_without_model_output() -> None:
    history = AgentStepHistory(
        history=[
            AgentStepRecord(
                model_output=None,
                result=[
                    ActionResult(
                        success=True,
                        extracted_content="Human clicked the cart icon",
                        action_name="click_element",
                    )
                ],
                state=type("State", (), {"url": "https://example.com", "title": "Shop"})(),
                metadata={"source": "human"},
            )
        ]
    )
    lines = TaskExtractorAgent.action_lines_from_history(history)
    assert any("Click the cart icon" == line or "cart icon" in line for line in lines)
    assert any(line.startswith("Click ") for line in lines)


def test_to_imperative_from_action_and_narration() -> None:
    convert = TaskExtractorAgent._to_imperative
    assert convert("click_element", "Human clicked ItemOne") == "Click ItemOne"
    assert convert("click_element", "Clicked ItemOne") == "Click ItemOne"
    assert convert("click_element", "Click ItemOne") == "Click ItemOne"
    assert convert("input_text", "Human entered 'x' in FieldA") == "Type 'x' in FieldA"
    assert convert("scroll_to_percent", "Human scrolled to 40%") == "Scroll to 40%"
    assert convert("scroll_to_percent", "Human scrolled horizontally to 80%") == (
        "Scroll horizontally to 80%"
    )
    assert convert("send_keys", "Human sent keys: Enter") == "Press Enter"
    assert convert("go_to_url", "Human navigated to https://example.com") == (
        "Go to https://example.com"
    )
    assert convert("", "Click ItemOne") == "Click ItemOne"
    assert TaskExtractorAgent.task_from_action_lines(
        ["Human clicked ItemOne", "Human scrolled to 10%"]
    ) == "1. Click ItemOne\n2. Scroll to 10%"

