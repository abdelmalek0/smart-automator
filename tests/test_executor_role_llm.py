"""Tests for per-role LLM binding in Executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.executor import Executor
from smart_automator.config import Config
from smart_automator.llm.base import BaseLLM


class _StubLLM(BaseLLM):
    def __init__(self, name: str):
        super().__init__()
        self._name = name

    @property
    def model_name(self) -> str | None:
        return self._name

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        return "ok"


class TestExecutorRoleLlmBinding(unittest.TestCase):
    @patch("smart_automator.agent.executor.ActionBuilder")
    @patch("smart_automator.agent.executor.HitlController")
    def test_action_critic_uses_planning_llm(self, _hitl, _actions):
        actions = MagicMock()
        actions.build_default_actions.return_value = {}
        _actions.return_value = actions

        nav_llm = _StubLLM("nav-model")
        plan_llm = _StubLLM("plan-model")
        config = Config(active_model="nav-model", planner_model="plan-model")
        browser = MagicMock()

        executor = Executor("task", browser, nav_llm, config, planner_llm=plan_llm)
        self.assertIs(executor._action_critic._llm, plan_llm)
        self.assertIs(executor._navigator._llm, nav_llm)
        self.assertIs(executor._planner._llm, plan_llm)


if __name__ == "__main__":
    unittest.main()
