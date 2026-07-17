"""Tests for replay action retry after wait on failure."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import NavigatorActionRegistry
from smart_automator.actions.schemas import Action
from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions
from smart_automator.agent.verification import PageSnapshot
from smart_automator.browser.dom import DOMElementNode, DOMState
from smart_automator.browser.views import BrowserState


def _node(index: int) -> DOMElementNode:
    return DOMElementNode(
        tag_name="button",
        xpath=f"/body/button[{index}]",
        highlight_index=index,
        attributes={"aria-label": f"btn-{index}"},
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


def _snapshot(url: str = "https://example.com", title: str = "Example") -> PageSnapshot:
    return PageSnapshot(url=url, title=title, scroll_y=0)


class TestReplayActionRetry(unittest.TestCase):
    def _make_registry(self) -> tuple[NavigatorActionRegistry, AgentContext, MagicMock, BrowserState]:
        context = AgentContext(
            "test",
            MagicMock(),
            MagicMock(),
            options=AgentOptions(action_delay_seconds=0, replay_action_retry_wait_seconds=15.0),
        )
        browser_context = context.browser_context
        page = MagicMock()
        page.get_cached_state.return_value = None
        browser_context.get_current_page.return_value = page
        browser_context.get_all_tab_ids.return_value = [0]

        element = _node(12)
        state = _browser_state("https://example.com", "Example", {12: element})
        dom_state = DOMState(element_tree=state.element_tree, selector_map=state.selector_map)
        page.get_dom_state.return_value = dom_state
        browser_context.get_state.return_value = state

        registry = NavigatorActionRegistry({"click_element": MagicMock()})
        return registry, context, browser_context, state

    @patch("smart_automator.actions.builder.apply_verification")
    @patch("smart_automator.actions.builder.probe_element")
    @patch("smart_automator.actions.builder.capture_page_snapshot")
    @patch("smart_automator.actions.builder.time.sleep")
    def test_retries_after_wait_when_first_attempt_fails(
        self,
        mock_sleep,
        mock_capture,
        _mock_probe,
        _mock_verify,
    ):
        registry, context, browser_context, state = self._make_registry()
        mock_capture.return_value = _snapshot()
        actions = [Action(name="click_element", args={"index": 12})]

        with patch.object(
            registry,
            "execute",
            side_effect=[
                ActionResult(error="Element with index 12 not found"),
                ActionResult(extracted_content="clicked"),
            ],
        ) as mock_execute:
            results = registry.execute_multi(
                actions,
                context,
                browser_state=state,
                action_retry_wait_seconds=15.0,
            )

        mock_sleep.assert_called_once_with(15.0)
        self.assertEqual(mock_execute.call_count, 2)
        browser_context.get_state.assert_called()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)

    @patch("smart_automator.actions.builder.apply_verification")
    @patch("smart_automator.actions.builder.probe_element")
    @patch("smart_automator.actions.builder.capture_page_snapshot")
    @patch("smart_automator.actions.builder.time.sleep")
    def test_fails_after_retry_when_both_attempts_fail(
        self,
        mock_sleep,
        mock_capture,
        _mock_probe,
        _mock_verify,
    ):
        registry, context, _browser_context, state = self._make_registry()
        mock_capture.return_value = _snapshot()
        actions = [Action(name="click_element", args={"index": 12})]
        error = ActionResult(error="Element with index 12 not found")

        with patch.object(registry, "execute", side_effect=[error, error]) as mock_execute:
            results = registry.execute_multi(
                actions,
                context,
                browser_state=state,
                action_retry_wait_seconds=15.0,
            )

        mock_sleep.assert_called_once_with(15.0)
        self.assertEqual(mock_execute.call_count, 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].error, "Element with index 12 not found")

    @patch("smart_automator.actions.builder.apply_verification")
    @patch("smart_automator.actions.builder.probe_element")
    @patch("smart_automator.actions.builder.capture_page_snapshot")
    @patch("smart_automator.actions.builder.time.sleep")
    def test_live_path_does_not_retry_without_param(
        self,
        mock_sleep,
        mock_capture,
        _mock_probe,
        _mock_verify,
    ):
        registry, context, _browser_context, state = self._make_registry()
        mock_capture.return_value = _snapshot()
        actions = [Action(name="click_element", args={"index": 12})]

        with patch.object(
            registry,
            "execute",
            return_value=ActionResult(error="Element with index 12 not found"),
        ) as mock_execute:
            results = registry.execute_multi(actions, context, browser_state=state)

        mock_sleep.assert_not_called()
        mock_execute.assert_called_once()
        self.assertEqual(results[0].error, "Element with index 12 not found")

    @patch("smart_automator.actions.builder.apply_verification")
    @patch("smart_automator.actions.builder.probe_element")
    @patch("smart_automator.actions.builder.capture_page_snapshot")
    @patch("smart_automator.actions.builder.time.sleep")
    def test_stopped_during_wait_skips_retry(
        self,
        mock_sleep,
        mock_capture,
        _mock_probe,
        _mock_verify,
    ):
        registry, context, _browser_context, state = self._make_registry()
        mock_capture.return_value = _snapshot()
        actions = [Action(name="click_element", args={"index": 12})]

        def stop_on_wait(_seconds: float) -> None:
            context.stopped = True

        mock_sleep.side_effect = stop_on_wait

        with patch.object(
            registry,
            "execute",
            return_value=ActionResult(error="Element with index 12 not found"),
        ) as mock_execute:
            results = registry.execute_multi(
                actions,
                context,
                browser_state=state,
                action_retry_wait_seconds=15.0,
            )

        mock_sleep.assert_called_once_with(15.0)
        mock_execute.assert_called_once()
        self.assertEqual(results[0].error, "Element with index 12 not found")


if __name__ == "__main__":
    unittest.main()
