import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import NavigatorActionRegistry
from smart_automator.actions.schemas import Action
from smart_automator.agent.context import ActionResult, AgentContext
from smart_automator.agent.verification import (
    VERIFICATION_FAILED,
    VERIFICATION_NO_EFFECT,
    VERIFICATION_VERIFIED,
    ElementLiveState,
    PageSnapshot,
    apply_verification,
    format_verification_hints,
    redact_input_message,
)
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.views import BrowserState


def _input_node(index: int, *, input_type: str = "text") -> DOMElementNode:
    return DOMElementNode(
        tag_name="input",
        xpath=f"/input[{index}]",
        highlight_index=index,
        attributes={"type": input_type, "placeholder": "field"},
    )


class TestVerificationPredicates(unittest.TestCase):
    def test_input_text_verified_when_live_value_matches(self):
        action = Action(name="input_text", args={"index": 1, "text": "hello"})
        result = ActionResult(extracted_content="typed")
        before = PageSnapshot(url="https://a", title="A", scroll_y=0)
        after = PageSnapshot(url="https://a", title="A", scroll_y=0)
        before_el = ElementLiveState(exists=True, value_length=0)
        after_el = ElementLiveState(exists=True, value_length=5, value_matches=True)
        apply_verification(
            action,
            result,
            before=before,
            after=after,
            before_element=before_el,
            after_element=after_el,
        )
        self.assertEqual(result.verification_status, VERIFICATION_VERIFIED)

    def test_input_text_failed_when_still_empty(self):
        action = Action(name="input_text", args={"index": 1, "text": "hello"})
        result = ActionResult(extracted_content="typed")
        before = PageSnapshot(url="https://a", title="A", scroll_y=0)
        after = PageSnapshot(url="https://a", title="A", scroll_y=0)
        apply_verification(
            action,
            result,
            before=before,
            after=after,
            before_element=ElementLiveState(exists=True),
            after_element=ElementLiveState(exists=True, value_length=0, value_matches=False),
        )
        self.assertEqual(result.verification_status, VERIFICATION_NO_EFFECT)

    def test_click_verified_on_dom_change(self):
        action = Action(name="click_element", args={"index": 2})
        result = ActionResult(extracted_content="clicked")
        before = PageSnapshot(url="https://a", title="A", scroll_y=0, dom_signature=1)
        after = PageSnapshot(url="https://a", title="A", scroll_y=0, dom_signature=2)
        apply_verification(
            action,
            result,
            before=before,
            after=after,
            before_element=ElementLiveState(exists=True),
            after_element=ElementLiveState(exists=True),
        )
        self.assertEqual(result.verification_status, VERIFICATION_VERIFIED)

    def test_click_no_effect_when_nothing_changes(self):
        action = Action(name="click_element", args={"index": 2})
        result = ActionResult(extracted_content="clicked")
        snapshot = PageSnapshot(url="https://a", title="A", scroll_y=0, dom_signature=1)
        apply_verification(
            action,
            result,
            before=snapshot,
            after=snapshot,
            before_element=ElementLiveState(exists=True),
            after_element=ElementLiveState(exists=True),
        )
        self.assertEqual(result.verification_status, VERIFICATION_NO_EFFECT)

    def test_password_redaction(self):
        message = redact_input_message(1, "secret-pass", _input_node(1, input_type="password"))
        self.assertNotIn("secret-pass", message)
        self.assertIn("len=11", message)

    def test_verification_hint_formats_issues(self):
        results = [
            ActionResult(
                action_name="click_element",
                action_index=2,
                verification_status=VERIFICATION_NO_EFFECT,
                verification_evidence="no observable page effect",
            ),
            ActionResult(
                action_name="input_text",
                action_index=1,
                verification_status=VERIFICATION_FAILED,
                verification_evidence="input still empty after typing",
            ),
        ]
        hint = format_verification_hints(results)
        self.assertIsNotNone(hint)
        self.assertIn("click_element [2]", hint)
        self.assertIn("input_text [1]", hint)

    def test_scroll_to_text_not_found_is_failed(self):
        snap = PageSnapshot(url="https://a", title="A", scroll_y=0)
        result = ActionResult(extracted_content="Text 'Refund' (occurrence 1) not found")
        apply_verification(
            Action(name="scroll_to_text", args={"text": "Refund"}),
            result,
            before=snap,
            after=snap,
            before_element=None,
            after_element=None,
        )
        self.assertEqual(result.verification_status, VERIFICATION_FAILED)

    def test_scroll_to_text_error_is_failed(self):
        snap = PageSnapshot(url="https://a", title="A", scroll_y=0)
        result = ActionResult(error="Text 'Refund' (occurrence 1) not found")
        apply_verification(
            Action(name="scroll_to_text", args={"text": "Refund"}),
            result,
            before=snap,
            after=snap,
            before_element=None,
            after_element=None,
        )
        self.assertEqual(result.verification_status, VERIFICATION_FAILED)


class TestExecuteMultiVerification(unittest.TestCase):
    def test_chains_multiple_input_text_actions(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.action_delay_seconds = 0
        browser_context = context.browser_context
        page = MagicMock()
        browser_context.get_current_page.return_value = page
        browser_context.get_all_tab_ids.return_value = {0}

        user = _input_node(0, input_type="text")
        password = _input_node(1, input_type="password")
        tree = DOMElementNode(tag_name="body", xpath="/body", children=[user, password])
        state = BrowserState(
            tab_id=0,
            url="https://example.com/login",
            title="Login",
            element_tree=tree,
            selector_map={0: user, 1: password},
        )
        browser_context.get_state.return_value = state

        snapshot = PageSnapshot(url=state.url, title=state.title, scroll_y=0, tab_ids=(0,))
        page.capture_snapshot.return_value = snapshot
        page.wait_for_page_stable.return_value = None

        registry = NavigatorActionRegistry({
            "input_text": lambda args, selector_map: ActionResult(
                extracted_content=f"typed {args['index']}",
                include_in_memory=True,
            ),
        })

        actions = [
            Action(name="input_text", args={"index": 0, "text": "user"}),
            Action(name="input_text", args={"index": 1, "text": "pass"}),
        ]

        with patch("smart_automator.actions.builder.capture_page_snapshot", return_value=snapshot):
            with patch(
                "smart_automator.actions.builder.probe_element",
                return_value=ElementLiveState(exists=True, value_matches=True, value_length=4),
            ):
                with patch("smart_automator.actions.builder.apply_verification") as verify:
                    verify.side_effect = lambda action, result, **kwargs: result
                    results = registry.execute_multi(actions, context, browser_state=state)

        self.assertEqual(len(results), 2)


class TestScrollToTextAction(unittest.TestCase):
    def test_missing_text_returns_error(self):
        from smart_automator.actions.builder import ActionBuilder

        context = AgentContext("test", MagicMock(), MagicMock())
        page = MagicMock()
        page.scroll_to_text.return_value = False
        context.browser_context.get_current_page.return_value = page
        registry = ActionBuilder(context).build_default_actions()
        result = registry.execute(Action(name="scroll_to_text", args={"text": "Refund"}), {})
        self.assertIsNotNone(result.error)
        self.assertIn("not found", result.error)
        page.scroll_to_text.assert_called_once_with("Refund", 1)

    def test_found_text_is_not_an_error(self):
        from smart_automator.actions.builder import ActionBuilder

        context = AgentContext("test", MagicMock(), MagicMock())
        page = MagicMock()
        page.scroll_to_text.return_value = True
        context.browser_context.get_current_page.return_value = page
        registry = ActionBuilder(context).build_default_actions()
        result = registry.execute(Action(name="scroll_to_text", args={"text": "Refund"}), {})
        self.assertIsNone(result.error)
        self.assertIn("Scrolled to text", result.extracted_content or "")


if __name__ == "__main__":
    unittest.main()
