import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import parse_actions
from smart_automator.agent.context import AgentContext
from smart_automator.agent.messages.utils import (
    coerce_navigator_response,
    extract_json_from_model_output,
    normalize_model_json,
)
from smart_automator.agent.executor import Executor
from smart_automator.agents.navigator import MAX_CONSECUTIVE_NO_ACTION_STEPS, NavigatorAgent

AGENT_OUTPUT_LOGIN = [
    {
        "name": "AgentOutput",
        "args": {
            "current_state": {
                "evaluation_previous_goal": "Unknown",
                "memory": "Need to log in",
                "next_goal": "Enter credentials",
            },
            "action": [
                {"input_text": {"index": 0, "text": "deligo-pos-01", "intent": "Enter username"}},
                {"input_text": {"index": 1, "text": "deligo-pos-01", "intent": "Enter password"}},
                {"click_element": {"index": 2, "intent": "Click SIGN IN"}},
            ],
        },
        "id": "4",
    }
]


class TestNormalizeModelJson(unittest.TestCase):
    def test_agent_output_list_unwraps(self):
        result = normalize_model_json(AGENT_OUTPUT_LOGIN)
        self.assertIn("action", result)
        self.assertEqual(len(result["action"]), 3)

    def test_flat_json(self):
        flat = {"current_state": {}, "action": [{"wait": {"seconds": 3}}]}
        result = normalize_model_json(flat)
        self.assertEqual(result["action"], [{"wait": {"seconds": 3}}])

    def test_actions_plural_alias(self):
        result = normalize_model_json({"actions": [{"wait": {"seconds": 1}}]})
        self.assertEqual(result["action"], [{"wait": {"seconds": 1}}])

    def test_empty_action_list(self):
        result = normalize_model_json({"current_state": {}, "action": []})
        self.assertEqual(result["action"], [])

    def test_split_list_state_and_actions(self):
        split = [
            {
                "current_state": {
                    "evaluation_previous_goal": "Success",
                    "memory": "PIN UI visible",
                    "next_goal": "Enter PIN",
                }
            },
            {"click_element": {"index": 5, "intent": "Press 0"}},
            {"click_element": {"index": 5, "intent": "Press 0 again"}},
        ]
        result = normalize_model_json(split)
        self.assertEqual(result["current_state"]["next_goal"], "Enter PIN")
        actions = parse_actions(result["action"], 10)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].name, "click_element")

    def test_state_only_list(self):
        result = normalize_model_json([
            {"current_state": {"evaluation_previous_goal": "Unknown", "memory": "waiting", "next_goal": "wait"}}
        ])
        self.assertIn("current_state", result)
        self.assertNotIn("action", result)


class TestExtractJsonFromModelOutput(unittest.TestCase):
    def test_parses_json_array(self):
        raw = '[{"current_state": {"memory": "x"}, "action": [{"wait": {"seconds": 1}}]}]'
        parsed = extract_json_from_model_output(raw)
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["action"][0]["wait"]["seconds"], 1)


class TestCoerceNavigatorResponse(unittest.TestCase):
    def test_agent_output_envelope_parses_to_three_actions(self):
        normalized = normalize_model_json(AGENT_OUTPUT_LOGIN)
        actions = parse_actions(normalized["action"], 10)
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0].name, "input_text")
        self.assertEqual(actions[2].name, "click_element")

    def test_nested_agent_output_in_action_field(self):
        wrapped = {
            "current_state": {"evaluation_previous_goal": "Unknown", "memory": "", "next_goal": ""},
            "action": AGENT_OUTPUT_LOGIN,
        }
        coerced = coerce_navigator_response(wrapped)
        actions = parse_actions(coerced["action"], 10)
        self.assertEqual(len(actions), 3)
        self.assertEqual(coerced["current_state"]["next_goal"], "Enter credentials")


class TestNoActionWaitPolicy(unittest.TestCase):
    def _make_navigator(self) -> NavigatorAgent:
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.max_actions_per_step = 10
        navigator = NavigatorAgent(MagicMock(), context, MagicMock(), MagicMock())
        return navigator

    def test_auto_wait_increments_streak(self):
        navigator = self._make_navigator()
        browser_state = MagicMock()
        browser_state.selector_map = {0: MagicMock(), 1: MagicMock()}

        with patch.object(navigator, "add_state_message_to_memory", return_value=browser_state):
            with patch.object(navigator, "remove_last_state_message_from_memory"):
                with patch.object(
                    navigator,
                    "get_json_response_with_raw",
                    return_value=({"current_state": {}, "action": []}, "{}"),
                ):
                    with patch.object(navigator._action_registry, "execute_multi", return_value=[]):
                        output = navigator.execute()

        self.assertFalse(output.get("error"))
        self.assertTrue(output["result"]["auto_wait"])
        self.assertEqual(navigator._context.consecutive_no_action_steps, 1)

    def test_real_actions_reset_streak(self):
        navigator = self._make_navigator()
        navigator._context.consecutive_no_action_steps = 2
        browser_state = MagicMock()
        browser_state.selector_map = {0: MagicMock()}

        response = {
            "current_state": {},
            "action": [{"click_element": {"index": 0, "intent": "click"}}],
        }

        with patch.object(navigator, "add_state_message_to_memory", return_value=browser_state):
            with patch.object(navigator, "remove_last_state_message_from_memory"):
                with patch.object(
                    navigator,
                    "get_json_response_with_raw",
                    return_value=(response, "{}"),
                ):
                    with patch.object(navigator._action_registry, "execute_multi", return_value=[]):
                        output = navigator.execute()

        self.assertFalse(output.get("error"))
        self.assertFalse(output["result"]["auto_wait"])
        self.assertEqual(navigator._context.consecutive_no_action_steps, 0)

    def test_three_consecutive_no_actions_escalates(self):
        navigator = self._make_navigator()
        navigator._context.consecutive_no_action_steps = MAX_CONSECUTIVE_NO_ACTION_STEPS - 1
        browser_state = MagicMock()
        browser_state.selector_map = {}
        browser_state.url = "https://example.com"
        browser_state.title = "Example"

        with patch.object(navigator, "add_state_message_to_memory", return_value=browser_state):
            with patch.object(navigator, "remove_last_state_message_from_memory"):
                with patch.object(
                    navigator,
                    "_invoke_navigator_with_recovery",
                    return_value=({"current_state": {}, "action": []}, "bad json", 0, []),
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


class TestExecutorFatalErrors(unittest.TestCase):
    def test_navigator_escalation_does_not_raise_immediately(self):
        browser_context = MagicMock()
        llm = MagicMock()
        config = MagicMock()
        config.max_input_tokens = 64000
        config.max_steps = 5
        config.max_actions_per_step = 5
        config.max_failures = 5
        config.planning_interval = 3
        config.include_attributes = []
        config.action_delay_seconds = 0
        config.max_observation_elements = 80
        config.max_observation_chars = 12000

        executor = Executor("task", browser_context, llm, config)
        nav_result = {
            "result": {
                "escalate_recovery": True,
                "auto_wait": True,
                "consecutive_no_action_steps": 2,
                "action_results": [],
                "page_url": "https://example.com",
                "page_title": "Example",
                "only_wait_actions": True,
                "only_done_action": False,
                "submit_hint_fired": False,
            }
        }

        with patch.object(executor, "_run_planner", return_value=None):
            with patch.object(executor._navigator, "execute", return_value=nav_result):
                outcome = executor._navigate()
                self.assertIsNone(outcome)
                self.assertEqual(executor.context.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
