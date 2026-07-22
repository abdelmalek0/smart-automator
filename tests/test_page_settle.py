"""Tests for page settle: network xhr/fetch tracking and DOM stability."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.browser.page import Page, _RELEVANT_RESOURCE_TYPES


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
            patch.object(page, "_wait_for_stable_network") as mock_network,
            patch.object(page, "_wait_for_dom_stable") as mock_dom,
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

        with (
            patch.object(page, "_wait_for_stable_network"),
            patch.object(page, "_wait_for_dom_stable"),
        ):
            mock_monotonic.side_effect = [0.0, 0.1]
            page.wait_for_page_stable()

        mock_sleep.assert_called_once_with(0.4)


if __name__ == "__main__":
    unittest.main()
