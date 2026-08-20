import unittest

from smart_automator.actions.schemas import Action
from smart_automator.agent.context import ActionResult
from smart_automator.agent.compound_integrity import (
    format_action_results_with_verification,
    format_all_actions_args,
)
from smart_automator.server.step_mapper import human_action_to_step, navigator_to_step


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

    def test_scroll_to_text_error_marks_step_failed(self):
        step = navigator_to_step(
            11,
            {
                "current_state": {"next_goal": "Scroll to find Refund button"},
                "actions": [Action(name="scroll_to_text", args={"text": "Refund"})],
                "action_results": [
                    ActionResult(
                        error="Text 'Refund' (occurrence 1) not found",
                        action_name="scroll_to_text",
                        verification_status="failed",
                    )
                ],
            },
        )
        self.assertEqual(step["status"], "fail")
        self.assertEqual(step["action"], "scroll_to_text")

    def test_human_action_to_step_uses_imperative_title(self):
        step = human_action_to_step(
            2,
            action="go_to_url",
            args={"url": "https://example.com"},
            result="Human navigated to https://example.com",
        )
        self.assertEqual(step["thought"], "Go to https://example.com")
        self.assertEqual(step["result"], "Human navigated to https://example.com")
        self.assertEqual(step["action"], "go_to_url")
        self.assertEqual(step["source"], "human")


if __name__ == "__main__":
    unittest.main()
