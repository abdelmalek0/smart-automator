import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.schemas import Action
from smart_automator.agent.context import AgentContext
from smart_automator.agents.navigator import MAX_CONSECUTIVE_NO_ACTION_STEPS, NavigatorAgent
from smart_automator.agents.recovery import (
    filter_actions_by_selector_map,
    format_valid_indices,
)


class TestRecoveryHelpers(unittest.TestCase):
    def test_format_valid_indices(self):
        self.assertEqual(format_valid_indices({}), "none (page may still be loading)")
        self.assertEqual(format_valid_indices({0: object(), 2: object()}), "[0, 2]")

    def test_filter_invalid_indexes(self):
        actions = [
            Action(name="click_element", args={"index": 1}),
            Action(name="click_element", args={"index": 99}),
        ]
        valid, invalid = filter_actions_by_selector_map(actions, {0: object(), 1: object()})
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0].index, 1)
        self.assertEqual(len(invalid), 1)

    def test_three_no_actions_escalates_instead_of_fatal(self):
        navigator = NavigatorAgent(MagicMock(), AgentContext("t", MagicMock(), MagicMock()), MagicMock(), MagicMock())
        navigator._context.consecutive_no_action_steps = MAX_CONSECUTIVE_NO_ACTION_STEPS - 1
        browser_state = MagicMock()
        browser_state.selector_map = {0: MagicMock(), 1: MagicMock()}
        browser_state.url = "https://example.com"
        browser_state.title = "Example"

        with patch.object(navigator, "add_state_message_to_memory", return_value=browser_state):
            with patch.object(navigator, "remove_last_state_message_from_memory"):
                with patch.object(
                    navigator,
                    "_invoke_navigator_with_recovery",
                    return_value=({"current_state": {}, "action": []}, "{}", 0, []),
                ):
                    with patch.object(navigator._action_registry, "execute_multi", return_value=[]):
                        with patch.object(
                            navigator._context.browser_context,
                            "get_state",
                            return_value=browser_state,
                        ):
                            output = navigator.execute()

        self.assertFalse(output.get("error"))
        self.assertTrue(output["result"]["escalate_recovery"])
        self.assertTrue(output["result"]["auto_wait"])


if __name__ == "__main__":
    unittest.main()
