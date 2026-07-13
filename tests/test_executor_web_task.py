import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.executor import Executor


class TestExecutorWebTask(unittest.TestCase):
    def _make_executor(self) -> Executor:
        browser_context = MagicMock()
        llm = MagicMock()
        config = MagicMock()
        config.max_input_tokens = 128000
        config.max_steps = 5
        config.max_actions_per_step = 5
        config.max_failures = 3
        config.planning_interval = 1
        config.include_attributes = []
        config.action_delay_seconds = 0
        return Executor("What is 2+2?", browser_context, llm, config)

    def test_non_web_task_returns_final_answer_without_navigation(self):
        executor = self._make_executor()
        plan = {
            "result": {
                "web_task": False,
                "done": True,
                "final_answer": "4",
            }
        }
        with patch.object(executor, "_run_planner", return_value=plan):
            with patch.object(executor, "_navigate") as navigate:
                result = executor.execute()
        navigate.assert_not_called()
        self.assertEqual(result, "4")

    def test_should_skip_navigation_when_web_task_false(self):
        executor = self._make_executor()
        plan = {
            "result": {
                "web_task": False,
                "done": False,
                "final_answer": "",
            }
        }
        self.assertTrue(executor._should_skip_navigation(plan))


if __name__ == "__main__":
    unittest.main()
