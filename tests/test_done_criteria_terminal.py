"""Tests for done confirmation → criteria finalize (no wait-burn loop)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions
from smart_automator.agent.executor import Executor
from smart_automator.agent.stuck_recovery import (
    build_premature_done_rejection_hint,
    should_block_navigator_done,
    update_page_progress,
)
from smart_automator.server.run_state import RunState
from smart_automator.server.runner import _apply_criteria_verdict


def _config(**overrides) -> MagicMock:
    config = MagicMock()
    config.headless = True
    config.max_steps = 10
    config.max_actions_per_step = 5
    config.max_failures = 5
    config.max_input_tokens = 1000
    config.planning_interval = 99
    config.include_attributes = []
    config.action_delay_seconds = 0
    config.replay_action_retry_wait_seconds = 0
    config.replay_show_highlights = False
    config.max_observation_elements = 10
    config.max_observation_chars = 1000
    config.hitl_timeout_minutes = 10
    config.max_unvalidated_dones = 2
    config.active_provider = "test"
    config.active_model = "test"
    config.llm_provider = "test"
    config.planner_llm_provider = ""
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _make_executor(**config_overrides) -> Executor:
    browser_context = MagicMock()
    llm = MagicMock()
    llm.model_name = "test"
    llm.get_accumulated_usage.return_value = {}
    llm.set_cancel_event = MagicMock()
    llm.set_interrupt_check = MagicMock()
    return Executor(
        "Complete checkout",
        browser_context,
        llm,
        _config(**config_overrides),
        success_criteria="Order confirmation visible",
    )


def _make_context() -> AgentContext:
    return AgentContext(
        task_id="test",
        browser_context=MagicMock(),
        message_manager=MagicMock(),
        options=AgentOptions(max_unvalidated_dones=2),
    )


class TestProgressClearsUnvalidatedDone(unittest.TestCase):
    def test_meaningful_progress_resets_unvalidated_and_recovery(self):
        context = _make_context()
        context.last_page_url = "https://example.com"
        context.last_page_title = "Home"
        context.consecutive_unvalidated_done = 1
        context.awaiting_done_recovery = True
        context.stuck_episode_active = True
        context.stale_steps_on_same_page = 2

        update_page_progress(
            context,
            url="https://example.com/next",
            title="Next",
            action_errors=False,
            auto_wait=False,
            submit_hint_fired=False,
            only_wait_actions=False,
        )

        self.assertEqual(context.consecutive_unvalidated_done, 0)
        self.assertFalse(context.awaiting_done_recovery)
        self.assertFalse(context.stuck_episode_active)
        self.assertFalse(should_block_navigator_done(context))


class TestPrematureDoneHint(unittest.TestCase):
    def test_hint_mentions_criteria_grade_terminal(self):
        hint = build_premature_done_rejection_hint(
            {"challenges": "Missing confirm", "next_steps": "Click Confirm"}
        )
        self.assertIn("criteria grade", hint.lower())
        self.assertIn("Click Confirm", hint)
        self.assertIn("Missing confirm", hint)


class TestFinalizeWithCriteria(unittest.TestCase):
    def test_confirm_done_finalizes_once_and_runner_dedupes(self):
        executor = _make_executor(planning_interval=99)
        plan = {
            "result": {
                "web_task": True,
                "done": True,
                "final_answer": "Order placed",
            }
        }
        verdict = {
            "passed": True,
            "evidence": "Thank you",
            "reason": "Confirmation visible",
        }

        with (
            patch.object(
                executor,
                "_run_planner",
                side_effect=[
                    {"result": {"done": False}},
                    plan,
                ],
            ),
            patch.object(
                executor,
                "_navigate",
                side_effect=self._nav_requested_done(executor),
            ),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.build_state_message",
                return_value="page state",
            ) as build_state,
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.check",
                return_value=dict(verdict),
            ) as check,
        ):
            result = executor.execute()

        self.assertEqual(result, "Order placed")
        self.assertEqual(executor.context.terminal_status, "pass")
        self.assertTrue(executor.context.criteria_verdict["passed"])
        check.assert_called_once()
        build_state.assert_called_once()

        run = RunState(
            run_id="run-dedupe",
            task="Complete checkout",
            headless=True,
            max_steps=10,
            success_criteria="Order confirmation visible",
            name="dedupe",
            user_id="test-user",
        )
        with patch(
            "smart_automator.server.runner.CriteriaCheckerAgent.check"
        ) as runner_check:
            _apply_criteria_verdict(run, executor, llm=MagicMock())
        runner_check.assert_not_called()
        self.assertEqual(run.status, "pass")
        self.assertTrue(run.criteria_verdict["passed"])

    @staticmethod
    def _nav_requested_done(executor: Executor):
        def _navigate():
            executor._last_nav_result = {
                "requested_done": True,
                "done_blocked": False,
                "only_wait_actions": False,
                "auto_wait": False,
                "action_results": [
                    ActionResult(is_done=True, extracted_content="Order placed")
                ],
            }
            executor.context.n_steps += 1
            return "requested_done"

        return _navigate

    def test_reject_once_continues_without_finalize(self):
        executor = _make_executor(planning_interval=99, max_steps=3)
        reject_plan = {
            "result": {
                "web_task": True,
                "done": False,
                "challenges": "Need confirm",
                "next_steps": "Click Confirm",
            }
        }
        nav_calls = {"n": 0}

        def navigate():
            nav_calls["n"] += 1
            if nav_calls["n"] == 1:
                executor._last_nav_result = {
                    "requested_done": True,
                    "done_blocked": False,
                    "action_results": [
                        ActionResult(is_done=True, extracted_content="done early")
                    ],
                }
                executor.context.n_steps += 1
                return "requested_done"
            # Recovery step with real actions (not idle wait)
            executor._last_nav_result = {
                "requested_done": False,
                "done_blocked": True,
                "only_wait_actions": False,
                "auto_wait": False,
                "action_results": [ActionResult(success=True, action_name="click_element")],
            }
            executor.context.n_steps += 1
            # Meaningful URL change clears recovery before escalate check
            update_page_progress(
                executor.context,
                url="https://example.com/confirm",
                title="Confirm",
                action_errors=False,
                auto_wait=False,
                submit_hint_fired=False,
                only_wait_actions=False,
            )
            executor.context.stopped = True
            return None

        with (
            patch.object(executor, "_run_planner", side_effect=[
                {"result": {"done": False}},
                reject_plan,
            ]),
            patch.object(executor, "_navigate", side_effect=navigate),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.check"
            ) as check,
        ):
            result = executor.execute()

        self.assertIsNone(result)
        check.assert_not_called()
        self.assertEqual(executor.context.consecutive_unvalidated_done, 0)
        self.assertFalse(executor.context.awaiting_done_recovery)
        self.assertGreaterEqual(nav_calls["n"], 2)

    def test_second_reject_finalizes(self):
        executor = _make_executor(planning_interval=99, max_unvalidated_dones=2)
        reject_plan = {"result": {"web_task": True, "done": False, "next_steps": "retry"}}
        nav_calls = {"n": 0}

        def navigate():
            nav_calls["n"] += 1
            executor._last_nav_result = {
                "requested_done": True,
                "done_blocked": False,
                "action_results": [
                    ActionResult(is_done=True, extracted_content=f"attempt {nav_calls['n']}")
                ],
            }
            executor.context.n_steps += 1
            # Simulate progress between dones so done is not permanently blocked
            if nav_calls["n"] == 2:
                executor.context.consecutive_unvalidated_done = 1
                executor.context.awaiting_done_recovery = False
                executor.context.stuck_episode_active = False
            return "requested_done"

        with (
            patch.object(
                executor,
                "_run_planner",
                side_effect=[
                    {"result": {"done": False}},
                    reject_plan,
                    reject_plan,
                ],
            ),
            patch.object(executor, "_navigate", side_effect=navigate),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.build_state_message",
                return_value="state",
            ),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.check",
                return_value={
                    "passed": False,
                    "evidence": "",
                    "reason": "Still missing confirmation",
                },
            ) as check,
        ):
            result = executor.execute()

        self.assertEqual(result, "attempt 2")
        self.assertEqual(executor.context.terminal_status, "fail")
        self.assertEqual(
            executor.context.criteria_verdict["reason"],
            "Still missing confirmation",
        )
        check.assert_called_once()
        self.assertEqual(nav_calls["n"], 2)

    def test_criteria_fail_sets_runner_fail_not_error(self):
        executor = _make_executor()
        executor.context.final_answer = "Done"
        executor.context.criteria_verdict = {
            "passed": False,
            "evidence": "No banner",
            "reason": "Success criteria not met",
            "observation_preview": "preview",
        }
        executor.context.terminal_status = "fail"

        run = RunState(
            run_id="run-fail",
            task="Complete checkout",
            headless=True,
            max_steps=10,
            success_criteria="Order confirmation visible",
            name="fail",
            user_id="test-user",
        )
        with patch(
            "smart_automator.server.runner.CriteriaCheckerAgent.check"
        ) as runner_check:
            _apply_criteria_verdict(run, executor, llm=MagicMock())
        runner_check.assert_not_called()
        self.assertEqual(run.status, "fail")
        self.assertNotEqual(run.status, "error")

    def test_wait_burn_after_reject_escalates(self):
        executor = _make_executor(planning_interval=99)
        reject_plan = {"result": {"web_task": True, "done": False, "next_steps": "Click X"}}
        nav_calls = {"n": 0}

        def navigate():
            nav_calls["n"] += 1
            if nav_calls["n"] == 1:
                executor._last_nav_result = {
                    "requested_done": True,
                    "done_blocked": False,
                    "action_results": [
                        ActionResult(is_done=True, extracted_content="premature")
                    ],
                }
                executor.context.n_steps += 1
                return "requested_done"
            executor._last_nav_result = {
                "requested_done": False,
                "done_blocked": True,
                "only_wait_actions": True,
                "auto_wait": False,
                "action_results": [
                    ActionResult(success=True, action_name="wait", extracted_content="waited")
                ],
            }
            executor.context.n_steps += 1
            return None

        with (
            patch.object(
                executor,
                "_run_planner",
                side_effect=[{"result": {"done": False}}, reject_plan],
            ),
            patch.object(executor, "_navigate", side_effect=navigate),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.build_state_message",
                return_value="state",
            ),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.check",
                return_value={
                    "passed": False,
                    "evidence": "",
                    "reason": "Criteria not met after idle wait",
                },
            ) as check,
        ):
            result = executor.execute()

        self.assertEqual(result, "Criteria not met after idle wait")
        self.assertEqual(executor.context.terminal_status, "fail")
        check.assert_called_once()
        self.assertEqual(nav_calls["n"], 2)


class TestPlannerIntervalFinalize(unittest.TestCase):
    def test_interval_planner_done_goes_through_criteria(self):
        executor = _make_executor(planning_interval=1)
        plan = {
            "result": {
                "web_task": True,
                "done": True,
                "final_answer": "Finished",
            }
        }
        with (
            patch.object(executor, "_run_planner", return_value=plan),
            patch.object(executor, "_navigate") as navigate,
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.build_state_message",
                return_value="state",
            ),
            patch(
                "smart_automator.agent.executor.CriteriaCheckerAgent.check",
                return_value={
                    "passed": True,
                    "evidence": "ok",
                    "reason": "met",
                },
            ) as check,
        ):
            result = executor.execute()

        navigate.assert_not_called()
        check.assert_called_once()
        self.assertEqual(result, "Finished")
        self.assertEqual(executor.context.terminal_status, "pass")


if __name__ == "__main__":
    unittest.main()
