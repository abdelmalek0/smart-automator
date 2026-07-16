import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import (
    NavigatorActionRegistry,
    _needs_inter_action_stable_wait,
)
from smart_automator.actions.schemas import Action
from smart_automator.agent.context import AgentContext
from smart_automator.agent.submit_hint import (
    build_submit_completeness_hint,
    find_submit_button_indices,
)
from smart_automator.browser.dom import DOMElementNode, DOMState
from smart_automator.browser.views import BrowserState


def _node(index: int, text: str, tag: str = "button") -> DOMElementNode:
    return DOMElementNode(
        tag_name=tag,
        xpath=f"/body/button[{index}]",
        highlight_index=index,
        attributes={"aria-label": text},
        children=[],
    )


def _browser_state(url: str, title: str, selector_map: dict[int, DOMElementNode]) -> BrowserState:
    tree = DOMElementNode(tag_name="body", xpath="/body", children=list(selector_map.values()))
    return BrowserState(
        tab_id=0,
        url=url,
        title=title,
        element_tree=tree,
        selector_map=selector_map,
    )


class TestSubmitCompletenessHint(unittest.TestCase):
    def test_finds_enter_button(self):
        selector_map = {
            0: _node(0, "0"),
            1: _node(1, "Enter"),
        }
        indices = find_submit_button_indices(selector_map)
        self.assertEqual(indices, [1])

    def test_hint_after_pin_digits_without_enter(self):
        before = _browser_state("https://pos.example/", "PIN", {0: _node(0, "0"), 1: _node(1, "Enter")})
        after = _browser_state("https://pos.example/", "PIN", {0: _node(0, "0"), 1: _node(1, "Enter")})
        actions = [
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
        ]
        hint = build_submit_completeness_hint(actions, before, after)
        self.assertIsNotNone(hint)
        self.assertIn("index(es) 1", hint)

    def test_no_hint_when_enter_clicked(self):
        before = _browser_state("https://pos.example/", "PIN", {0: _node(0, "0"), 1: _node(1, "Enter")})
        after = before
        actions = [
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 1}),
        ]
        self.assertIsNone(build_submit_completeness_hint(actions, before, after))


class TestExecuteMultiClicks(unittest.TestCase):
    def test_runs_multiple_clicks_on_same_screen(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.action_delay_seconds = 0
        browser_context = context.browser_context
        page = MagicMock()
        page.get_cached_state.return_value = None
        browser_context.get_current_page.return_value = page

        digit = _node(0, "0")
        state = _browser_state("https://pos.example/", "PIN", {0: digit})
        dom_state = DOMState(element_tree=state.element_tree, selector_map=state.selector_map)
        page.get_dom_state.return_value = dom_state
        browser_context.get_state.return_value = state

        registry = NavigatorActionRegistry({
            "click_element": lambda args, selector_map: __import__(
                "smart_automator.agent.context", fromlist=["ActionResult"]
            ).ActionResult(),
        })
        actions = [
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
        ]

        with patch.object(browser_context, "remove_highlight"):
            results = registry.execute_multi(actions, context, browser_state=state)

        self.assertEqual(len(results), 3)


class TestConservativeWaitDeduplication(unittest.TestCase):
    def test_inter_action_wait_skipped_for_last_action(self):
        action = Action(name="click_element", args={"index": 0})
        self.assertFalse(_needs_inter_action_stable_wait(action, is_last_in_batch=True))

    def test_inter_action_wait_kept_between_batch_actions(self):
        action = Action(name="click_element", args={"index": 0})
        self.assertTrue(_needs_inter_action_stable_wait(action, is_last_in_batch=False))

    def test_single_click_batch_defers_stable_waits(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.action_delay_seconds = 0
        browser_context = context.browser_context
        page = MagicMock()
        page.get_cached_state.return_value = None
        browser_context.get_current_page.return_value = page

        digit = _node(0, "0")
        state = _browser_state("https://pos.example/", "PIN", {0: digit})
        dom_state = DOMState(element_tree=state.element_tree, selector_map=state.selector_map)
        page.get_dom_state.return_value = dom_state
        browser_context.get_state.return_value = state

        registry = NavigatorActionRegistry({
            "click_element": lambda args, selector_map: __import__(
                "smart_automator.agent.context", fromlist=["ActionResult"]
            ).ActionResult(),
        })
        actions = [Action(name="click_element", args={"index": 0})]

        with patch.object(browser_context, "remove_highlight"):
            registry.execute_multi(actions, context, browser_state=state)

        page.set_defer_post_action_stable.assert_any_call(True)
        page.set_defer_post_action_stable.assert_any_call(False)
        page.wait_for_page_stable.assert_not_called()

    def test_multi_click_batch_waits_only_between_actions(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        context.options.action_delay_seconds = 0
        browser_context = context.browser_context
        page = MagicMock()
        page.get_cached_state.return_value = None
        browser_context.get_current_page.return_value = page

        digit = _node(0, "0")
        state = _browser_state("https://pos.example/", "PIN", {0: digit})
        dom_state = DOMState(element_tree=state.element_tree, selector_map=state.selector_map)
        page.get_dom_state.return_value = dom_state
        browser_context.get_state.return_value = state

        registry = NavigatorActionRegistry({
            "click_element": lambda args, selector_map: __import__(
                "smart_automator.agent.context", fromlist=["ActionResult"]
            ).ActionResult(),
        })
        actions = [
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
            Action(name="click_element", args={"index": 0}),
        ]

        with patch.object(browser_context, "remove_highlight"):
            registry.execute_multi(actions, context, browser_state=state)

        self.assertEqual(page.wait_for_page_stable.call_count, 2)


if __name__ == "__main__":
    unittest.main()
