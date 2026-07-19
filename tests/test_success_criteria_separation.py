import unittest
from unittest.mock import MagicMock

from smart_automator.agent.context import AgentContext, AgentOptions
from smart_automator.agent.messages.service import MessageManager
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.views import BrowserState
from smart_automator.utils.prompts import build_browser_state_message


class TestSuccessCriteriaSeparation(unittest.TestCase):
    def test_init_task_messages_separates_criteria_from_ultimate_task(self):
        manager = MessageManager()
        manager.init_task_messages(
            "system",
            "Task: Add item to cart",
            success_criteria="Cart shows one item",
        )
        user_messages = [
            stored.message["content"]
            for stored in manager.history.messages
            if stored.message.get("role") == "user"
        ]
        ultimate = next(msg for msg in user_messages if "Your ultimate task is" in msg)
        criteria = next(
            msg
            for msg in user_messages
            if "Success criteria (observations to VERIFY" in msg
        )
        self.assertIn("Add item to cart", ultimate)
        self.assertNotIn("Success criteria", ultimate)
        self.assertIn("Cart shows one item", criteria)
        self.assertIn("do NOT execute these as browser actions", criteria)

    def test_build_browser_state_message_includes_criteria_block(self):
        browser_context = MagicMock()
        message_manager = MagicMock()
        context = AgentContext(
            task_id="t1",
            browser_context=browser_context,
            message_manager=message_manager,
            options=AgentOptions(),
        )
        context.success_criteria = "Order confirmation is visible"
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com/checkout",
            title="Checkout",
            element_tree=DOMElementNode(tag_name="body", xpath="/body"),
            selector_map={},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )

        message = build_browser_state_message(context, browser_state)

        self.assertIn("Success criteria to verify (read-only — not actions):", message)
        self.assertIn("Order confirmation is visible", message)


if __name__ == "__main__":
    unittest.main()
