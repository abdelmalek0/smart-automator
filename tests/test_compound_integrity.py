import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import NavigatorActionRegistry
from smart_automator.actions.schemas import Action
from smart_automator.agent.compound_integrity import (
    build_post_commit_no_wait_hint,
    is_commit_action,
    reverify_mutations,
    BatchState,
    MutationRecord,
)
from smart_automator.agent.context import ActionResult, AgentContext
from smart_automator.agent.verification import (
    VERIFICATION_FAILED,
    VERIFICATION_VERIFIED,
    ElementLiveState,
    PageSnapshot,
)
from smart_automator.agents.output_schemas import validate_action_args
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.views import BrowserState


def _input_node(index: int, *, input_type: str = "text", placeholder: str = "field") -> DOMElementNode:
    return DOMElementNode(
        tag_name="input",
        xpath=f"/input[{index}]",
        highlight_index=index,
        attributes={"type": input_type, "placeholder": placeholder},
    )


def _button_node(index: int, text: str) -> DOMElementNode:
    return DOMElementNode(
        tag_name="button",
        xpath=f"/button[{index}]",
        highlight_index=index,
        attributes={},
        children=[DOMElementNode(tag_name="text", xpath=f"/button[{index}]/text", children=[], attributes={})],
    )


class TestCompoundHelpers(unittest.TestCase):
    def test_is_commit_action_detects_submit_button(self):
        submit = DOMElementNode(
            tag_name="button",
            xpath="/button[1]",
            highlight_index=2,
            attributes={},
            children=[
                DOMElementNode(
                    tag_name="text",
                    xpath="/button[1]/text",
                    children=[],
                    attributes={},
                )
            ],
        )
        submit.children[0].children = []  # type: ignore[attr-defined]
        action = Action(name="click_element", args={"index": 2})
        self.assertTrue(is_commit_action(action, submit))

    def test_wait_duration_alias_validated(self):
        validated = validate_action_args("wait", {"duration": 5})
        self.assertEqual(validated["seconds"], 5)

    def test_post_commit_no_wait_hint_when_only_wait_planned(self):
        context = AgentContext("t", MagicMock(), MagicMock())
        context.last_step_had_commit = True
        context.last_commit_snapshot = PageSnapshot(
            url="https://example.com/login",
            title="Login",
            scroll_y=0,
        )
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com/login",
            title="Login",
            element_tree=DOMElementNode(tag_name="body", xpath="/body"),
            selector_map={},
        )
        hint = build_post_commit_no_wait_hint(
            context,
            browser_state,
            [Action(name="wait", args={"seconds": 3})],
        )
        self.assertIsNotNone(hint)
        self.assertIn("do not wait", hint.lower())


class TestCommitBarrier(unittest.TestCase):
    def _registry_with_handlers(self, context: AgentContext):
        return NavigatorActionRegistry({
            "input_text": lambda args, selector_map: ActionResult(
                extracted_content=f"typed {args['index']}",
                include_in_memory=True,
            ),
            "click_element": lambda args, selector_map: ActionResult(
                extracted_content=f"clicked {args['index']}",
                include_in_memory=True,
            ),
        })

    def _base_state(self):
        user = _input_node(0, placeholder="email")
        password = _input_node(1, input_type="password", placeholder="password")
        submit = _button_node(2, "Sign in")
        tree = DOMElementNode(tag_name="body", xpath="/body", children=[user, password, submit])
        return BrowserState(
            tab_id=0,
            url="https://example.com/login",
            title="Login",
            element_tree=tree,
            selector_map={0: user, 1: password, 2: submit},
        )

    def test_password_verify_failure_blocks_submit(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.action_delay_seconds = 0
        browser_context = context.browser_context
        page = MagicMock()
        browser_context.get_current_page.return_value = page
        browser_context.get_all_tab_ids.return_value = {0}
        state = self._base_state()
        browser_context.get_state.return_value = state
        snapshot = PageSnapshot(url=state.url, title=state.title, scroll_y=0, tab_ids=(0,))
        page.capture_snapshot.return_value = snapshot
        page.wait_for_page_stable.return_value = None

        registry = self._registry_with_handlers(context)
        actions = [
            Action(name="input_text", args={"index": 0, "text": "user@example.com"}),
            Action(name="input_text", args={"index": 1, "text": "secret-password"}),
            Action(name="click_element", args={"index": 2}),
        ]

        probe_values = [
            ElementLiveState(exists=True, value_matches=True, value_length=16),
            ElementLiveState(exists=True, value_length=0, value_matches=False),
        ]

        def fake_probe(page, element, **kwargs):
            if kwargs.get("expected_value") == "secret-password":
                return ElementLiveState(exists=True, value_length=0, value_matches=False)
            if kwargs.get("expected_value") == "user@example.com":
                return ElementLiveState(exists=True, value_matches=True, value_length=16)
            return ElementLiveState(exists=True, value_length=0)

        with patch("smart_automator.actions.builder.capture_page_snapshot", return_value=snapshot):
            with patch("smart_automator.actions.builder.probe_element", side_effect=fake_probe):
                with patch("smart_automator.actions.builder.apply_verification") as verify:
                    def apply_side_effect(action, result, **kwargs):
                        if action.name == "input_text" and action.args.get("index") == 1:
                            result.verification_status = VERIFICATION_FAILED
                            result.verification_evidence = "input still empty after typing"
                        elif action.name == "input_text":
                            result.verification_status = VERIFICATION_VERIFIED
                        return result

                    verify.side_effect = apply_side_effect
                    results = registry.execute_multi(actions, context, browser_state=state)

        self.assertEqual(len(results), 2)
        self.assertFalse(any("clicked" in (r.extracted_content or "") for r in results))

    def test_username_regression_blocks_submit(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.action_delay_seconds = 0
        browser_context = context.browser_context
        page = MagicMock()
        browser_context.get_current_page.return_value = page
        browser_context.get_all_tab_ids.return_value = {0}
        state = self._base_state()
        browser_context.get_state.return_value = state
        snapshot = PageSnapshot(url=state.url, title=state.title, scroll_y=0, tab_ids=(0,))
        page.capture_snapshot.return_value = snapshot
        page.wait_for_page_stable.return_value = None

        registry = self._registry_with_handlers(context)
        actions = [
            Action(name="input_text", args={"index": 0, "text": "user@example.com"}),
            Action(name="input_text", args={"index": 1, "text": "secret-password"}),
            Action(name="click_element", args={"index": 2}),
        ]

        batch = BatchState(
            mutations=[
                MutationRecord(
                    action=actions[0],
                    element=state.selector_map[0],
                    expected_value="user@example.com",
                ),
                MutationRecord(
                    action=actions[1],
                    element=state.selector_map[1],
                    expected_value="secret-password",
                ),
            ]
        )

        def fake_reverify(page, batch_state):
            return False, ["[0] empty after mutation"]

        with patch("smart_automator.actions.builder.capture_page_snapshot", return_value=snapshot):
            with patch(
                "smart_automator.actions.builder.probe_element",
                return_value=ElementLiveState(exists=True, value_matches=True, value_length=16),
            ):
                with patch("smart_automator.actions.builder.apply_verification") as verify:
                    verify.side_effect = lambda action, result, **kwargs: setattr(
                        result, "verification_status", VERIFICATION_VERIFIED
                    ) or result
                    with patch("smart_automator.actions.builder.reverify_mutations", side_effect=fake_reverify):
                        results = registry.execute_multi(actions, context, browser_state=state)

        blocked = [r for r in results if "Commit blocked" in (r.extracted_content or "")]
        self.assertEqual(len(blocked), 1)
        self.assertIn("[0]", blocked[0].extracted_content or "")

    def test_wait_uses_duration_alias(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        registry = NavigatorActionRegistry({
            "wait": lambda args, selector_map: ActionResult(
                extracted_content=f"Waited {args.get('seconds', args.get('duration', 3))} seconds",
                include_in_memory=True,
            ),
        })
        result = registry.execute(
            Action(name="wait", args={"duration": 5}),
            {},
        )
        self.assertIn("5", result.extracted_content or "")


class TestReverifyMutations(unittest.TestCase):
    def test_detects_empty_username(self):
        user = _input_node(0)
        action = Action(name="input_text", args={"index": 0, "text": "user"})
        batch = BatchState(
            mutations=[MutationRecord(action=action, element=user, expected_value="user")]
        )
        page = MagicMock()
        with patch(
            "smart_automator.agent.compound_integrity.probe_element",
            return_value=ElementLiveState(exists=True, value_length=0, value_matches=False),
        ):
            ok, issues = reverify_mutations(page, batch)
        self.assertFalse(ok)
        self.assertTrue(any("[0]" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
