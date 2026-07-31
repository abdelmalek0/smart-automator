"""Tests for page settle: network xhr/fetch tracking and DOM stability."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.browser.page import (
    Page,
    _RELEVANT_RESOURCE_TYPES,
    _evaluate_resilient,
    _is_destroyed_context_error,
)


class TestPageSettle(unittest.TestCase):
    def test_relevant_resource_types_include_xhr_and_fetch(self):
        self.assertIn("xhr", _RELEVANT_RESOURCE_TYPES)
        self.assertIn("fetch", _RELEVANT_RESOURCE_TYPES)

    @patch("smart_automator.browser.page.time.sleep")
    @patch("smart_automator.browser.page.time.monotonic")
    def test_wait_for_stable_network_waits_for_xhr(self, mock_monotonic, mock_sleep):
        pw_page = MagicMock()
        listeners: dict[str, object] = {}
        pw_page.on.side_effect = lambda event, handler: listeners.__setitem__(event, handler)

        xhr_request = MagicMock()
        xhr_request.resource_type = "xhr"
        xhr_request.url = "https://example.com/api/cart"
        xhr_request.headers = {}

        clock = {"now": 0.0}
        mock_monotonic.side_effect = lambda: clock["now"]

        def sleep_side_effect(_seconds):
            clock["now"] += 0.1
            if mock_sleep.call_count == 1:
                listeners["request"](xhr_request)
            elif mock_sleep.call_count == 2:
                response = MagicMock()
                response.request = xhr_request
                response.headers = {"content-type": "application/json"}
                listeners["response"](response)

        mock_sleep.side_effect = sleep_side_effect

        page = Page(
            pw_page,
            page_id=0,
            wait_for_network_idle_page_load_time=0.5,
            maximum_wait_page_load_time=2.0,
        )

        page._wait_for_stable_network()

        self.assertIn("request", listeners)
        self.assertIn("response", listeners)
        self.assertGreaterEqual(mock_sleep.call_count, 2)

    @patch("smart_automator.browser.page.time.sleep")
    @patch("smart_automator.browser.page.time.monotonic")
    def test_wait_for_dom_stable_waits_until_signature_is_unchanged(self, mock_monotonic, mock_sleep):
        pw_page = MagicMock()
        page = Page(
            pw_page,
            page_id=0,
            wait_for_network_idle_page_load_time=0.5,
            maximum_wait_page_load_time=2.0,
        )

        clock = {"now": 0.0}
        mock_monotonic.side_effect = lambda: clock["now"]
        mock_sleep.side_effect = lambda _seconds: clock.__setitem__("now", clock["now"] + 0.2)

        signatures = iter([
            '{"interactive":0,"textLen":0,"textSample":""}',
            '{"interactive":2,"textLen":42,"textSample":"Cart"}',
        ])
        stable_signature = '{"interactive":2,"textLen":42,"textSample":"Cart"}'

        def probe_side_effect():
            try:
                return next(signatures)
            except StopIteration:
                return stable_signature

        with patch.object(page, "_probe_dom_signature", side_effect=probe_side_effect) as mock_probe:
            page._wait_for_dom_stable()

        self.assertGreaterEqual(mock_probe.call_count, 4)
        mock_sleep.assert_called()

    @patch("smart_automator.browser.page.time.sleep")
    @patch("smart_automator.browser.page.time.monotonic")
    def test_wait_for_page_stable_runs_network_and_dom_settle(self, mock_monotonic, mock_sleep):
        pw_page = MagicMock()
        page = Page(pw_page, page_id=0)

        with (
            patch.object(page, "_wait_for_stable_network", return_value=False) as mock_network,
            patch.object(page, "_wait_for_dom_stable", return_value=False) as mock_dom,
        ):
            mock_monotonic.side_effect = [0.0, 0.3]
            page.wait_for_page_stable()

        mock_network.assert_called_once()
        mock_dom.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("smart_automator.browser.page.time.sleep")
    @patch("smart_automator.browser.page.time.monotonic")
    def test_wait_for_page_stable_applies_minimum_wait_after_settle(self, mock_monotonic, mock_sleep):
        pw_page = MagicMock()
        page = Page(
            pw_page,
            page_id=0,
            minimum_wait_page_load_time=0.5,
        )
        clock = {"now": 0.1}
        bootstrap = iter([0.0, 0.1])

        def monotonic_side_effect():
            try:
                return next(bootstrap)
            except StopIteration:
                return clock["now"]

        mock_monotonic.side_effect = monotonic_side_effect
        mock_sleep.side_effect = lambda seconds: clock.__setitem__(
            "now", clock["now"] + seconds
        )

        with (
            patch.object(page, "_wait_for_stable_network", return_value=False),
            patch.object(page, "_wait_for_dom_stable", return_value=False),
        ):
            page.wait_for_page_stable()

        total_slept = sum(call.args[0] for call in mock_sleep.call_args_list)
        self.assertAlmostEqual(total_slept, 0.4, places=1)

    def test_get_dom_state_returns_minimal_state_when_aborted(self):
        pw_page = MagicMock()
        page = Page(pw_page, page_id=0)
        with patch("smart_automator.browser.page.build_dom_tree") as mock_build:
            state = page.get_dom_state(should_abort=lambda: True)
        mock_build.assert_not_called()
        self.assertEqual(state.selector_map, {})
        self.assertEqual(state.element_tree.tag_name, "body")

    def test_is_destroyed_context_error_matches_playwright_navigation_message(self):
        exc = RuntimeError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
        )
        self.assertTrue(_is_destroyed_context_error(exc))
        self.assertFalse(_is_destroyed_context_error(RuntimeError("element not found")))

    def test_evaluate_resilient_retries_after_destroyed_context(self):
        destroyed = RuntimeError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
        )
        evaluate_fn = MagicMock(side_effect=[destroyed, {"ok": True}])
        settle = MagicMock()

        result = _evaluate_resilient(evaluate_fn, "script", settle=settle)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(evaluate_fn.call_count, 2)
        settle.assert_called_once()

    def test_evaluate_resilient_reraises_non_navigation_errors(self):
        evaluate_fn = MagicMock(side_effect=RuntimeError("element not found"))
        with self.assertRaisesRegex(RuntimeError, "element not found"):
            _evaluate_resilient(evaluate_fn, "script")

    def test_evaluate_resilient_swallows_destroyed_context_when_requested(self):
        destroyed = RuntimeError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
        )
        evaluate_fn = MagicMock(side_effect=destroyed)

        result = _evaluate_resilient(
            evaluate_fn,
            "script",
            settle=MagicMock(),
            swallow_destroyed=True,
        )

        self.assertIsNone(result)
        self.assertEqual(evaluate_fn.call_count, 3)

    def test_get_scroll_info_retries_after_destroyed_context(self):
        pw_page = MagicMock()
        page = Page(pw_page, page_id=0)
        destroyed = RuntimeError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
        )
        pw_page.evaluate.reset_mock()
        pw_page.evaluate.side_effect = [
            destroyed,
            {"scrollY": 120, "viewportHeight": 800, "scrollHeight": 2400},
        ]

        with patch.object(page, "_settle_after_navigation_race") as mock_settle:
            scroll_y, viewport_h, scroll_h = page.get_scroll_info()

        self.assertEqual((scroll_y, viewport_h, scroll_h), (120, 800, 2400))
        mock_settle.assert_called_once()
        self.assertEqual(pw_page.evaluate.call_count, 2)

    def test_get_scroll_info_reraises_after_exhausted_retries(self):
        pw_page = MagicMock()
        page = Page(pw_page, page_id=0)
        destroyed = RuntimeError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
        )
        pw_page.evaluate.reset_mock()
        pw_page.evaluate.side_effect = destroyed

        with patch.object(page, "_settle_after_navigation_race"):
            with self.assertRaises(RuntimeError):
                page.get_scroll_info()
        self.assertEqual(pw_page.evaluate.call_count, 3)

    def test_click_element_treats_destroyed_context_on_fallback_as_navigation(self):
        pw_page = MagicMock()
        page = Page(pw_page, page_id=0)
        element = MagicMock()
        element.highlight_index = 1
        element.xpath = "/body/button[1]"
        handle = MagicMock()
        handle.click.side_effect = RuntimeError("click timeout")
        destroyed = RuntimeError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
        )
        handle.evaluate.side_effect = destroyed

        with (
            patch.object(page, "_locate_element_with_retry", return_value=handle),
            patch.object(page, "_scroll_into_view_if_needed"),
            patch.object(page, "_evaluate_on_handle", return_value=None) as mock_evaluate,
            patch.object(page, "_maybe_wait_after_interaction") as mock_wait,
            patch.object(page, "_check_and_handle_navigation") as mock_nav,
        ):
            page.click_element(element)

        mock_evaluate.assert_called_once_with(
            handle,
            "el => el.click()",
            swallow_destroyed=True,
        )
        mock_wait.assert_called_once()
        mock_nav.assert_called_once()


if __name__ == "__main__":
    unittest.main()
