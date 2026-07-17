"""Tests for history replay remapping fallbacks."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.schemas import Action
from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions
from smart_automator.agent.history import AgentStepRecord, BrowserStateHistory
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.history import (
    DOMHistoryElement,
    find_element_by_id_in_tree,
    find_element_by_xpath_in_tree,
    resolve_history_element_in_tree,
)
from smart_automator.browser.views import BrowserState
from smart_automator.reporting.replay_script import build_replay_action_args


class TestBuildReplayActionArgs(unittest.TestCase):
    def test_injects_xpath_and_drops_index(self):
        element = {
            "xpath": "html/body/input[1]",
            "cssSelector": "input#email",
        }
        args = build_replay_action_args(
            "input_text",
            {"index": 0, "text": "user"},
            element,
        )
        self.assertEqual(args["xpath"], "html/body/input[1]")
        self.assertEqual(args["css_selector"], "input#email")
        self.assertNotIn("index", args)

    def test_non_dom_action_unchanged(self):
        args = build_replay_action_args("wait", {"seconds": 3}, {"xpath": "/x"})
        self.assertEqual(args, {"seconds": 3})


class TestFindElementByXpath(unittest.TestCase):
    def test_finds_node_by_normalized_xpath(self):
        target = DOMElementNode(tag_name="input", xpath="html/body/input[1]", highlight_index=2)
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[target])
        target.parent = root

        found = find_element_by_xpath_in_tree("/html/body/input[1]", root)
        self.assertIs(found, target)


class TestResolveHistoryElement(unittest.TestCase):
    def test_id_fallback_when_hash_match_fails(self):
        historical = DOMHistoryElement(
            tag_name="flt-semantics",
            xpath="html/body/other",
            highlight_index=1,
            attributes={"id": "flt-semantic-node-38", "aria-label": "Abdul Bassit"},
        )
        target = DOMElementNode(
            tag_name="flt-semantics",
            xpath="html/body/changed",
            highlight_index=3,
            attributes={"id": "flt-semantic-node-38", "style": "transform: matrix(1,0,0,1,0,8)"},
        )
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[target])
        target.parent = root

        found = resolve_history_element_in_tree(historical, root)
        self.assertIs(found, target)

    def test_aria_label_fallback_before_xpath(self):
        historical = DOMHistoryElement(
            tag_name="flt-semantics",
            xpath="html/body/missing",
            highlight_index=1,
            attributes={"aria-label": "Abdul Bassit"},
        )
        target = DOMElementNode(
            tag_name="flt-semantics",
            xpath="html/body/current",
            highlight_index=2,
            attributes={"aria-label": "Abdul Bassit"},
        )
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[target])
        target.parent = root

        found = resolve_history_element_in_tree(historical, root)
        self.assertIs(found, target)

    def test_find_element_by_id_in_tree(self):
        target = DOMElementNode(
            tag_name="button",
            xpath="html/body/button[1]",
            attributes={"id": "submit-btn"},
        )
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[target])
        target.parent = root

        found = find_element_by_id_in_tree("submit-btn", root)
        self.assertIs(found, target)


class TestNavigatorReplayRemapping(unittest.TestCase):
    def _make_navigator(self):
        from smart_automator.agents.navigator import NavigatorAgent

        context = MagicMock(spec=AgentContext)
        context.options = AgentOptions(max_actions_per_step=5, replay_show_highlights=False)
        context.browser_context = MagicMock()
        context.stopped = False
        context.paused = False

        navigator = NavigatorAgent(
            llm=MagicMock(),
            context=context,
            message_manager=MagicMock(),
            action_registry=MagicMock(),
        )
        return navigator, context

    def test_wait_retry_remaps_after_second_attempt(self):
        navigator, context = self._make_navigator()

        historical = DOMHistoryElement(
            tag_name="input",
            xpath="html/body/input[1]",
            highlight_index=0,
            attributes={"aria-label": "Email"},
        )
        raw_action = {"input_text": {"index": 0, "text": "user"}}
        element = DOMElementNode(tag_name="input", xpath="html/body/input[1]", highlight_index=5)
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[element])
        element.parent = root

        empty_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=DOMElementNode(tag_name="body", xpath="html/body"),
            selector_map={},
        )
        loaded_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=root,
            selector_map={5: element},
        )
        context.browser_context.get_state.side_effect = [empty_state, loaded_state]

        with patch.object(navigator, "update_action_indices", side_effect=[None, {"input_text": {"index": 5, "text": "user"}}]):
            updated, overrides, _state = navigator._remap_single_history_action(
                historical,
                raw_action,
                empty_state,
            )

        self.assertEqual(updated, {"input_text": {"index": 5, "text": "user"}})
        self.assertEqual(overrides, {})
        self.assertEqual(context.browser_context.get_state.call_count, 1)
        context.browser_context.get_state.assert_called_with(
            show_highlights=False,
            wait_for_stable=True,
        )

    def test_id_fallback_injects_selector_override(self):
        navigator, context = self._make_navigator()

        historical = DOMHistoryElement(
            tag_name="flt-semantics",
            xpath="html/body/old",
            highlight_index=1,
            attributes={"id": "flt-semantic-node-38", "aria-label": "Abdul Bassit"},
        )
        raw_action = {"click_element": {"index": 1, "intent": "Select employee"}}
        element = DOMElementNode(
            tag_name="flt-semantics",
            xpath="html/body/new",
            highlight_index=4,
            attributes={"id": "flt-semantic-node-38"},
        )
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[element])
        element.parent = root
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=root,
            selector_map={},
        )
        context.browser_context.get_state.return_value = browser_state

        with patch.object(navigator, "update_action_indices", return_value=None):
            updated, overrides, _state = navigator._remap_single_history_action(
                historical,
                raw_action,
                browser_state,
            )

        self.assertEqual(updated, {"click_element": {"index": 4, "intent": "Select employee"}})
        self.assertIn(4, overrides)
        self.assertIs(overrides[4], element)

    def test_execute_history_actions_uses_no_highlights_by_default(self):
        navigator, context = self._make_navigator()
        history_item = AgentStepRecord(
            model_output='{"action":[{"wait":{"seconds":1}}]}',
            result=[],
            state=BrowserStateHistory(url="https://example.com", title="Example", tabs=[]),
        )
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=DOMElementNode(tag_name="body", xpath="html/body"),
            selector_map={},
        )
        context.browser_context.get_state.return_value = browser_state
        navigator._action_registry.execute_multi.return_value = []

        navigator.execute_history_actions(history_item, [{"wait": {"seconds": 1}}], 0.0)

        context.browser_context.get_state.assert_called_with(
            show_highlights=False,
            wait_for_stable=True,
        )

    @patch("smart_automator.agents.navigator.time.sleep")
    def test_remapping_retries_after_wait(self, mock_sleep):
        navigator, context = self._make_navigator()
        context.options.replay_action_retry_wait_seconds = 15.0
        history_item = AgentStepRecord(
            model_output='{"action":[{"click_element":{"index":1}}]}',
            result=[],
            state=BrowserStateHistory(
                url="https://example.com",
                title="Example",
                tabs=[],
                interacted_elements=[
                    DOMHistoryElement(
                        tag_name="button",
                        xpath="html/body/button[1]",
                        highlight_index=1,
                        attributes={"id": "btn-1"},
                    )
                ],
            ),
        )
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=DOMElementNode(tag_name="body", xpath="html/body"),
            selector_map={},
        )
        refreshed_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=DOMElementNode(tag_name="body", xpath="html/body"),
            selector_map={2: DOMElementNode(tag_name="button", xpath="html/body/button[1]", highlight_index=2)},
        )
        context.browser_context.get_state.side_effect = [browser_state, refreshed_state]
        navigator._action_registry.execute_multi.return_value = [ActionResult()]

        remap_results = [
            (None, {}, browser_state),
            ({"click_element": {"index": 2}}, {2: DOMElementNode(tag_name="button", xpath="html/body/button[1]", highlight_index=2)}, refreshed_state),
        ]
        with patch.object(navigator, "_remap_single_history_action", side_effect=remap_results):
            results = navigator.execute_history_actions(
                history_item,
                [{"click_element": {"index": 1}}],
                0.0,
            )

        mock_sleep.assert_called_once_with(15.0)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)
        navigator._action_registry.execute_multi.assert_called_once()

    def test_xpath_fallback_injects_selector_override(self):
        navigator, context = self._make_navigator()

        historical = DOMHistoryElement(
            tag_name="input",
            xpath="html/body/input[1]",
            highlight_index=0,
            attributes={"aria-label": "Email"},
            css_selector="input[aria-label='Email']",
        )
        raw_action = {"input_text": {"index": 0, "text": "user"}}
        element = DOMElementNode(tag_name="input", xpath="html/body/input[1]", highlight_index=None)
        root = DOMElementNode(tag_name="body", xpath="html/body", children=[element])
        element.parent = root
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            tabs=[],
            element_tree=root,
            selector_map={},
        )
        context.browser_context.get_state.return_value = browser_state

        with patch.object(navigator, "update_action_indices", return_value=None):
            updated, overrides, _state = navigator._remap_single_history_action(
                historical,
                raw_action,
                browser_state,
            )

        self.assertEqual(updated, {"input_text": {"index": 0, "text": "user"}})
        self.assertIn(0, overrides)
        self.assertIs(overrides[0], element)

    def test_execute_history_actions_reports_failed_action_names(self):
        navigator, context = self._make_navigator()
        context.options.replay_action_retry_wait_seconds = 0.0
        history_item = AgentStepRecord(
            model_output='{"action":[{"click_element":{"index":1}}]}',
            result=[],
            state=BrowserStateHistory(url="https://example.com/login", title="Login", tabs=[]),
        )

        with patch.object(navigator, "_remap_single_history_action", return_value=(None, {}, BrowserState(
            tab_id=0,
            url="https://example.com/login",
            title="Login",
            tabs=[],
            element_tree=DOMElementNode(tag_name="body", xpath="html/body"),
            selector_map={},
        ))):
            results = navigator.execute_history_actions(history_item, [{"click_element": {"index": 1}}], 0.0)

        self.assertTrue(results[0].error)
        self.assertIn("https://example.com/login", results[0].error)
        self.assertIn("click_element", results[0].error)


if __name__ == "__main__":
    unittest.main()
