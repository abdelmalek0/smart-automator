"""Tests that the criteria checker uses earlier screen excerpts for then-vs-now checks."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.context import AgentContext, AgentOptions, AgentStepInfo
from smart_automator.agent.findings import ScreenExcerpt, is_referential_criteria
from smart_automator.agents.criteria_checker import CriteriaCheckerAgent
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.views import BrowserState
from smart_automator.utils.prompts import build_browser_state_message


class TestCriteriaCheckerExcerpts(unittest.TestCase):
    def test_present_only_prompt_has_no_excerpt_block(self):
        captured: dict = {}

        class Checker(CriteriaCheckerAgent):
            def get_json_response(self, messages, temperature=0.1):
                captured["content"] = messages[1]["content"]
                return {"passed": True, "evidence": "ok", "reason": "visible"}

        checker = Checker(MagicMock())
        verdict = checker.check(
            task="Open dashboard",
            success_criteria="Dashboard is visible",
            state_message="[Visible text]\nDashboard\n",
            referential=False,
        )
        self.assertTrue(verdict["passed"])
        self.assertNotIn("Earlier screens", captured["content"])
        self.assertNotIn("Earlier screens: none", captured["content"])

    def test_referential_check_includes_excerpts_not_memory(self):
        captured: dict = {}

        class Checker(CriteriaCheckerAgent):
            def get_json_response(self, messages, temperature=0.1):
                captured["system"] = messages[0]["content"]
                captured["content"] = messages[1]["content"]
                return {
                    "passed": True,
                    "evidence": "total 20.00 matches earlier 20.00",
                    "reason": "now vs then",
                }

        excerpts = [
            ScreenExcerpt(
                step=8,
                url="https://pos.example/",
                title="Cart",
                text="Hot Chocolate\n20.00",
            )
        ]
        checker = Checker(MagicMock())
        verdict = checker.check(
            task="Refund the order",
            success_criteria="Total Refund matches the amount we paid",
            state_message="[Visible text]\nTotal Refund\n20.00\n",
            final_answer="I remember paying $99.00",
            excerpts=excerpts,
            referential=True,
        )
        self.assertTrue(verdict["passed"])
        self.assertIn("Earlier screens", captured["content"])
        self.assertIn("20.00", captured["content"])
        self.assertIn("Hot Chocolate", captured["content"])
        self.assertIn("only allowed evidence for what was true then", captured["system"])
        self.assertIn("Do not use completion notes", captured["system"])
        self.assertNotIn("Earlier screens: none", captured["content"])

    def test_fail_closed_note_when_no_excerpts(self):
        captured: dict = {}

        class Checker(CriteriaCheckerAgent):
            def get_json_response(self, messages, temperature=0.1):
                captured["content"] = messages[1]["content"]
                return {
                    "passed": False,
                    "evidence": "",
                    "reason": "no earlier screen copy",
                }

        checker = Checker(MagicMock())
        verdict = checker.check(
            task="Register",
            success_criteria="The confirmation shows the same username we entered",
            state_message="[Visible text]\nWelcome\n",
            excerpts=[],
            referential=True,
        )
        self.assertFalse(verdict["passed"])
        self.assertIn("Earlier screens: none", captured["content"])
        self.assertIn("passed=false", captured["content"])

    def test_state_message_hint_only_when_referential(self):
        context = AgentContext(
            task_id="t1",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        context.success_criteria = "Order confirmation is visible"
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com/done",
            title="Done",
            element_tree=DOMElementNode(tag_name="body", xpath="/body"),
            selector_map={},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )
        with patch(
            "smart_automator.utils.prompts.collect_accessible_names_section",
            return_value="",
        ):
            present = build_browser_state_message(context, browser_state)
        self.assertNotIn("recorded automatically", present)

        context.success_criteria = "Checkout total matches the amount we paid"
        context.referential_criteria = is_referential_criteria(context.success_criteria)
        with patch(
            "smart_automator.utils.prompts.collect_accessible_names_section",
            return_value="",
        ):
            referential = build_browser_state_message(context, browser_state)
        self.assertIn("recorded automatically", referential)

    def test_build_state_message_captures_verbatim_copy(self):
        browser_context = MagicMock()
        browser_state = BrowserState(
            tab_id=0,
            url="https://pos.example/",
            title="Shift",
            element_tree=DOMElementNode(tag_name="body", xpath="/body"),
            selector_map={},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )
        browser_context.get_state.return_value = browser_state
        context = AgentContext(
            task_id="t1",
            browser_context=browser_context,
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        context.step_info = AgentStepInfo(step_number=20, max_steps=30)
        context.referential_criteria = True
        with patch(
            "smart_automator.agents.criteria_checker.build_browser_state_message",
            return_value="[Visible text]\nTotal Refund\n20.00\n",
        ):
            CriteriaCheckerAgent.build_state_message(context)
        self.assertEqual(len(context.screen_excerpts), 1)
        self.assertIn("20.00", context.screen_excerpts[0].text)
        self.assertIn("Total Refund", context.screen_excerpts[0].text)

    def test_executor_enables_excerpts_only_for_referential_criteria(self):
        from smart_automator.agent.executor import Executor

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

        browser_context = MagicMock()
        llm = MagicMock()
        llm.model_name = "test"
        llm.get_accumulated_usage.return_value = {}
        llm.set_cancel_event = MagicMock()
        llm.set_interrupt_check = MagicMock()
        present = Executor(
            "Open dashboard",
            browser_context,
            llm,
            config,
            success_criteria="Dashboard is visible",
        )
        self.assertFalse(present.context.referential_criteria)

        referential = Executor(
            "Buy the mug",
            browser_context,
            llm,
            config,
            success_criteria="Checkout total matches the amount we paid",
        )
        self.assertTrue(referential.context.referential_criteria)


if __name__ == "__main__":
    unittest.main()
