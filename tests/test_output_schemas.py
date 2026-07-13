import unittest

from smart_automator.agents.output_schemas import (
    validate_navigator_output,
    validate_planner_output,
)


class TestOutputSchemas(unittest.TestCase):
    def test_validate_navigator_output_coerces_index(self):
        result = validate_navigator_output(
            {
                "current_state": {"memory": "x"},
                "action": [{"click_element": {"index": "3", "intent": "click"}}],
            }
        )
        self.assertEqual(result["action"][0]["click_element"]["index"], 3)

    def test_validate_navigator_output_rejects_unknown_action(self):
        result = validate_navigator_output(
            {"action": [{"not_real": {"index": 1}}]}
        )
        self.assertEqual(result["action"], [])

    def test_validate_planner_output_coerces_bools(self):
        result = validate_planner_output(
            {
                "done": "true",
                "web_task": "false",
                "final_answer": "42",
            }
        )
        self.assertTrue(result["done"])
        self.assertFalse(result["web_task"])


if __name__ == "__main__":
    unittest.main()
