import unittest

from smart_automator.actions.schemas import Action
from smart_automator.agent.context import ActionResult
from smart_automator.agent.compound_integrity import (
    format_action_results_with_verification,
    format_all_actions_args,
)
from smart_automator.server.step_mapper import navigator_to_step


class TestStepMapper(unittest.TestCase):
    def test_navigator_to_step_includes_all_actions(self):
        actions = [
            Action(name="input_text", args={"index": 0, "text": "user"}),
            Action(name="input_text", args={"index": 1, "text": "pass"}),
            Action(name="click_element", args={"index": 2, "intent": "Submit"}),
        ]
        results = [
            ActionResult(
                extracted_content="Typed 'user' into element 0",
                action_name="input_text",
                action_index=0,
                verification_status="verified",
                verification_evidence="value set (len=4)",
            ),
            ActionResult(
                extracted_content="Typed into element 1 (len=4)",
                action_name="input_text",
                action_index=1,
                verification_status="verified",
                verification_evidence="value set (len=4)",
            ),
            ActionResult(
                extracted_content="Clicked element 2",
                action_name="click_element",
                action_index=2,
                verification_status="no_effect",
                verification_evidence="no observable page effect",
            ),
        ]
        step = navigator_to_step(
            3,
            {
                "current_state": {"next_goal": "Log in"},
                "actions": actions,
                "action_results": results,
            },
        )
        self.assertEqual(step["action"], "input_text, input_text, click_element")
        self.assertIn("actions", step["args"])
        self.assertEqual(len(step["args"]["actions"]), 3)
        self.assertIn("click_element [2]: no_effect", step["result"])

    def test_format_all_actions_args(self):
        actions = [
            Action(name="input_text", args={"index": 0, "text": "a"}),
            Action(name="click_element", args={"index": 2}),
        ]
        payload = format_all_actions_args(actions)
        self.assertEqual(len(payload["actions"]), 2)

    def test_format_action_results_with_verification(self):
        text = format_action_results_with_verification([
            ActionResult(
                extracted_content="Clicked element 2",
                action_name="click_element",
                action_index=2,
                verification_status="verified",
                verification_evidence="DOM update",
            )
        ])
        self.assertIn("click_element [2]: verified", text)


if __name__ == "__main__":
    unittest.main()
