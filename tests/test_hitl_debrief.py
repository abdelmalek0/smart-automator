import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions, PendingHitlHandoff
from smart_automator.agent.hitl import HitlController
from smart_automator.agents.hitl_debrief import HitlDebriefAgent
from smart_automator.agents.output_schemas import validate_hitl_debrief_output


def _make_context() -> AgentContext:
    context = AgentContext(
        task_id="test",
        browser_context=MagicMock(),
        message_manager=MagicMock(),
        options=AgentOptions(),
    )
    context.message_manager.get_messages.return_value = [
        {"role": "user", "content": "<nano_user_request>Buy item</nano_user_request>"}
    ]
    return context


class HitlDebriefAgentTests(unittest.TestCase):
    def test_validate_hitl_debrief_output_normalizes_enums(self):
        result = validate_hitl_debrief_output(
            {
                "inferred_reason": "Completed login",
                "goal_achieved": "Signed in",
                "outcome": "not-real",
                "evidence": "Dashboard visible",
                "remaining_work": "Continue checkout",
                "confidence": "bogus",
            }
        )
        self.assertEqual(result["outcome"], "unclear")
        self.assertEqual(result["confidence"], "low")

    def test_analyze_includes_intervention_context(self):
        context = _make_context()
        agent = HitlDebriefAgent(MagicMock(), context.message_manager, context=context)
        handoff = PendingHitlHandoff(
            recorded=[
                (
                    "click_element",
                    {"xpath": "html/body/button"},
                    ActionResult(success=True, extracted_content="Human clicked button"),
                )
            ],
            intervention_reason="CAPTCHA on login page",
            intervention_source="agent",
            cycle=1,
            start_url="https://example.com/login",
            start_title="Login",
            end_url="https://example.com/dashboard",
            end_title="Dashboard",
        )

        with patch.object(
            agent,
            "get_json_response",
            return_value={
                "inferred_reason": "Solved CAPTCHA and logged in",
                "goal_achieved": "Reached dashboard",
                "outcome": "achieved",
                "evidence": "Dashboard visible",
                "remaining_work": "Continue purchase",
                "confidence": "high",
            },
        ) as response_mock:
            result = agent.analyze(task="Buy item", handoff=handoff)

        self.assertEqual(result["outcome"], "achieved")
        user_message = response_mock.call_args[0][0][1]["content"]
        self.assertIn("CAPTCHA on login page", user_message)
        self.assertIn("Human clicked button", user_message)

    def test_format_human_memory_message_uses_analysis(self):
        recorded = [
            (
                "input_text",
                {"text": "secret", "xpath": "html/body/input"},
                ActionResult(success=True, extracted_content="Human entered text in input"),
            )
        ]
        message = HitlController.format_human_memory_message(
            recorded,
            intervention_reason="Need help",
            intervention_source="agent",
            analysis={
                "inferred_reason": "Entered credentials",
                "goal_achieved": "Logged in",
                "outcome": "achieved",
                "evidence": "Dashboard visible",
                "remaining_work": "Continue task",
                "confidence": "high",
            },
        )
        self.assertIn("Entered credentials", message)
        self.assertIn("Logged in", message)
        self.assertIn("Human action trace:", message)
        self.assertIn("[redacted]", message)
        self.assertNotIn("secret", message)

    def test_analyze_omits_prior_agent_action_results_from_state(self):
        context = _make_context()
        context.action_results = [
            ActionResult(error="prior agent failure"),
        ]
        agent = HitlDebriefAgent(MagicMock(), context.message_manager, context=context)
        handoff = PendingHitlHandoff(
            recorded=[],
            intervention_reason="Manual take control",
            intervention_source="manual",
            cycle=1,
            start_url="https://example.com",
            start_title="Home",
            end_url="https://example.com",
            end_title="Home",
        )
        browser_state = MagicMock()
        browser_state.element_tree = None
        browser_state.selector_map = {}
        browser_state.tab_id = 1
        browser_state.url = "https://example.com"
        browser_state.title = "Home"
        browser_state.tabs = []
        browser_state.scroll_height = 100
        browser_state.scroll_y = 0
        browser_state.visual_viewport_height = 100
        context.browser_context.get_state.return_value = browser_state

        with patch.object(
            agent,
            "get_json_response",
            return_value={
                "inferred_reason": "",
                "goal_achieved": "",
                "outcome": "unclear",
                "evidence": "",
                "remaining_work": "",
                "confidence": "low",
            },
        ) as response_mock:
            agent.analyze(task="Complete task", handoff=handoff)

        messages = response_mock.call_args[0][0]
        state_blob = messages[1]["content"]
        self.assertNotIn("prior agent failure", state_blob)


if __name__ == "__main__":
    unittest.main()
