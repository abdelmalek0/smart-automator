"""Tests for saved replay step execution."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.reporting.replay_executor import (
    _resolve_locator,
    execute_replay_steps,
)
from smart_automator.reporting.replay_script import _playwright_locator, _sanitize_css_for_flutter


class TestReplayExecutor(unittest.TestCase):
    def test_resolve_locator_prefers_aria_label(self):
        page = MagicMock()
        step = {
            "action": "click_element",
            "args": {"xpath": "html/body/button"},
            "element": {
                "attributes": {"id": "flt-semantic-node-38", "aria-label": "Abdul Bassit"},
            },
        }

        _resolve_locator(page, step)

        page.get_by_label.assert_called_once_with("Abdul Bassit")

    def test_resolve_locator_uses_id_without_label(self):
        page = MagicMock()
        step = {
            "action": "click_element",
            "args": {},
            "element": {"attributes": {"id": "submit-btn"}},
        }

        _resolve_locator(page, step)

        page.locator.assert_called_once_with("#submit-btn")

    def test_resolve_locator_skips_flutter_id_for_css(self):
        page = MagicMock()
        css = (
            'html > body > flt-semantics:nth-of-type(1)'
            '[id="flt-semantic-node-18"][role="button"]'
        )
        step = {
            "action": "click_element",
            "args": {"css_selector": css},
            "element": {"attributes": {"id": "flt-semantic-node-18", "role": "button"}},
        }

        _resolve_locator(page, step)

        page.locator.assert_called_once_with(_sanitize_css_for_flutter(css))
        self.assertNotIn("flt-semantic-node-18", page.locator.call_args[0][0])

    def test_playwright_locator_skips_flutter_id_for_css(self):
        css = (
            'html > body > flt-semantics:nth-of-type(1)'
            '[id="flt-semantic-node-18"][role="button"]'
        )
        step = {
            "action": "click_element",
            "args": {"css_selector": css},
            "element": {"attributes": {"id": "flt-semantic-node-18"}},
        }

        locator_expr = _playwright_locator(step)

        self.assertIn("flt-semantics:nth-of-type(1)", locator_expr)
        self.assertNotIn("flt-semantic-node-18", locator_expr)

    def test_settle_wait_after_successful_click(self):
        browser_context = MagicMock()
        page_wrapper = MagicMock()
        page = MagicMock()
        locator = MagicMock()
        page.locator.return_value = locator
        page_wrapper.playwright_page = page
        browser_context.get_current_page.return_value = page_wrapper

        steps = [
            {
                "action": "click_element",
                "args": {},
                "element": {"attributes": {"id": "submit-btn"}},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        page_wrapper.wait_for_page_stable.assert_called_once()
        page.wait_for_timeout.assert_not_called()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)

    def test_execute_click_uses_id_locator(self):
        browser_context = MagicMock()
        page = MagicMock()
        locator = MagicMock()
        page.locator.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "click_element",
                "args": {},
                "element": {"attributes": {"id": "submit-btn"}},
                "element_label": "<button#submit-btn>",
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        page.locator.assert_called_with("#submit-btn")
        locator.click.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)

    @patch("smart_automator.reporting.replay_executor.time.sleep")
    def test_retries_failed_step_after_wait(self, mock_sleep):
        browser_context = MagicMock()
        page = MagicMock()
        locator = MagicMock()
        locator.click.side_effect = [RuntimeError("not ready"), None]
        page.locator.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "click_element",
                "args": {},
                "element": {"attributes": {"id": "btn"}},
            }
        ]

        results = execute_replay_steps(
            browser_context,
            steps,
            action_retry_wait_seconds=15.0,
        )

        mock_sleep.assert_called_once_with(15.0)
        self.assertEqual(locator.click.call_count, 2)
        self.assertIsNone(results[0].error)


if __name__ == "__main__":
    unittest.main()
