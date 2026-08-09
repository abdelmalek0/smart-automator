"""Tests for script replay always ending with criteria check."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.context import ActionResult
from smart_automator.server.run_state import RunState
from smart_automator.server.runner import run_automation


class TestScriptReplayCriteria(unittest.TestCase):
    @patch("smart_automator.server.runner.local_browser_mode_enabled", return_value=True)
    @patch("smart_automator.server.runner._generate_report")
    @patch("smart_automator.server.runner.save_run_history")
    @patch("smart_automator.server.runner._apply_criteria_verdict")
    @patch("smart_automator.server.runner._script_replay_with_events")
    @patch("smart_automator.server.runner.Executor")
    @patch("smart_automator.server.runner.BrowserContext")
    @patch("smart_automator.server.runner.create_llm")
    @patch("smart_automator.server.runner.config_for_run")
    @patch("smart_automator.server.runner.load_run_replay")
    def test_criteria_runs_after_script_step_failure(
        self,
        mock_load_replay,
        mock_config_for_run,
        mock_create_llm,
        mock_browser_context_cls,
        mock_executor_cls,
        mock_script_replay,
        mock_apply_criteria,
        mock_save_history,
        mock_generate_report,
        mock_local_browser,
    ) -> None:
        mock_load_replay.return_value = {
            "replay_steps": [{"action": "click_element", "args": {}}],
        }
        mock_script_replay.return_value = [
            ActionResult(error="Locator.click: Timeout 30000ms exceeded."),
        ]

        mock_config = MagicMock()
        mock_config.replay_action_retry_wait_seconds = 0.0
        mock_config_for_run.return_value = mock_config
        mock_create_llm.return_value = MagicMock()

        browser_context = MagicMock()
        mock_browser_context_cls.return_value = browser_context

        executor = MagicMock()
        executor.context.history.history = []
        mock_executor_cls.return_value = executor

        run = RunState(
            run_id="replay-run",
            task="Replay POS flow",
            headless=True,
            max_steps=10,
            success_criteria="Order total is visible",
            user_id="test-user",
            source_run_id="source-run",
            use_replay_script=True,
        )

        run_automation(run)

        mock_script_replay.assert_called_once()
        mock_apply_criteria.assert_called_once_with(run, executor, mock_create_llm.return_value)


class TestTrainingRerun(unittest.TestCase):
    @patch("smart_automator.server.runner.local_browser_mode_enabled", return_value=True)
    @patch("smart_automator.server.runner._generate_report")
    @patch("smart_automator.server.runner.save_run_history")
    @patch("smart_automator.server.runner._apply_criteria_verdict")
    @patch("smart_automator.server.runner.load_run_replay")
    @patch("smart_automator.server.runner.Executor")
    @patch("smart_automator.server.runner.BrowserContext")
    @patch("smart_automator.server.runner.create_llm")
    @patch("smart_automator.server.runner.config_for_run")
    def test_training_rerun_executes_llm_not_script_replay(
        self,
        mock_config_for_run,
        mock_create_llm,
        mock_browser_context_cls,
        mock_executor_cls,
        mock_load_replay,
        mock_apply_criteria,
        mock_save_history,
        mock_generate_report,
        mock_local_browser,
    ) -> None:
        mock_config = MagicMock()
        mock_config_for_run.return_value = mock_config
        mock_create_llm.return_value = MagicMock()

        browser_context = MagicMock()
        mock_browser_context_cls.return_value = browser_context

        executor = MagicMock()
        executor.execute.return_value = True
        executor.context.history.history = []
        executor.context.hitl_timed_out = False
        mock_executor_cls.return_value = executor

        run = RunState(
            run_id="training-rerun",
            task="Retrain POS flow",
            headless=False,
            max_steps=10,
            success_criteria="Order total is visible",
            user_id="test-user",
            source_run_id="source-run",
            use_replay_script=False,
        )

        run_automation(run)

        mock_load_replay.assert_not_called()
        executor.execute.assert_called_once()
        mock_apply_criteria.assert_called_once_with(run, executor, mock_create_llm.return_value)
        self.assertTrue(executor.context.hitl_enabled)


if __name__ == "__main__":
    unittest.main()
