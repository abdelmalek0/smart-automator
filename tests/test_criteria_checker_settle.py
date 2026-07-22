"""Tests for criteria checker page settle before snapshot."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from smart_automator.agent.context import AgentContext, AgentOptions
from smart_automator.agents.criteria_checker import CriteriaCheckerAgent
from smart_automator.browser.views import BrowserState
from smart_automator.browser.dom import DOMElementNode


class TestCriteriaCheckerSettle(unittest.TestCase):
    def test_build_state_message_waits_for_stable(self):
        browser_context = MagicMock()
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
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

        message = CriteriaCheckerAgent.build_state_message(context)

        browser_context.get_state.assert_called_once_with(
            show_highlights=False,
            wait_for_stable=True,
        )
        self.assertIn("https://example.com", message)


if __name__ == "__main__":
    unittest.main()
