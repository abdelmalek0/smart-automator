"""Tests for saved replay step execution."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.reporting.replay_executor import (
    _resolve_locator,
    execute_replay_steps,
)
from smart_automator.reporting.replay_script import (
    _format_element_label,
    _playwright_locator,
    _sanitize_css_for_flutter,
)


class TestReplayExecutor(unittest.TestCase):
    @staticmethod
    def _unique_locator() -> MagicMock:
        locator = MagicMock()
        locator.count.return_value = 1
        return locator

    def test_resolve_locator_prefers_aria_label(self):
        page = MagicMock()
        page.get_by_label.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {"xpath": "html/body/button"},
            "element": {
                "attributes": {"id": "flt-semantic-node-38", "aria-label": "Abdul Bassit"},
            },
        }

        _resolve_locator(page, step)

        page.get_by_label.assert_called_once_with("Abdul Bassit", exact=True)

    def test_resolve_locator_uses_id_without_label(self):
        page = MagicMock()
        page.locator.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {},
            "element": {"attributes": {"id": "submit-btn"}},
        }

        _resolve_locator(page, step)

        page.locator.assert_called_once_with("#submit-btn")

    def test_resolve_locator_skips_flutter_id_for_css(self):
        page = MagicMock()
        page.locator.return_value = self._unique_locator()
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

    def test_resolve_locator_uses_role_and_accessible_name_for_flutter(self):
        page = MagicMock()
        page.get_by_role.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {
                "css_selector": (
                    'html > body > flt-semantics:nth-of-type(4)[role="button"]'
                    '[id="flt-semantic-node-8"]'
                ),
            },
            "element": {
                "attributes": {"id": "flt-semantic-node-8", "role": "button"},
                "accessibleName": "Continue",
            },
        }

        resolved = _resolve_locator(page, step)

        page.get_by_role.assert_called_once_with("button", name="Continue", exact=True)
        page.locator.assert_not_called()
        self.assertIs(resolved, page.get_by_role.return_value)

    def test_resolve_locator_falls_back_when_role_is_ambiguous(self):
        page = MagicMock()
        role_locator = MagicMock()
        role_locator.count.return_value = 2
        css_locator = self._unique_locator()
        page.get_by_role.return_value = role_locator
        page.locator.return_value = css_locator
        css = (
            'html > body > flt-semantics:nth-of-type(4)[role="button"]'
            '[id="flt-semantic-node-8"]'
        )
        step = {
            "action": "click_element",
            "args": {"css_selector": css},
            "element": {
                "attributes": {"id": "flt-semantic-node-8", "role": "button"},
                "accessibleName": "Meals",
            },
        }

        resolved = _resolve_locator(page, step)

        page.get_by_role.assert_called_once_with("button", name="Meals", exact=True)
        page.locator.assert_called_once_with(_sanitize_css_for_flutter(css))
        self.assertIs(resolved, css_locator)

    def test_playwright_locator_uses_role_and_accessible_name_for_flutter(self):
        step = {
            "action": "click_element",
            "args": {
                "css_selector": (
                    'html > body > flt-semantics:nth-of-type(4)[role="button"]'
                    '[id="flt-semantic-node-8"]'
                ),
            },
            "element": {
                "attributes": {"id": "flt-semantic-node-8", "role": "button"},
                "accessibleName": "Continue",
            },
        }

        locator_expr = _playwright_locator(step)

        self.assertEqual(
            locator_expr,
            "page.get_by_role('button', name='Continue', exact=True)",
        )

    def test_format_element_label_prefers_accessible_name_over_flutter_id(self):
        label = _format_element_label(
            {
                "tagName": "flt-semantics",
                "attributes": {"id": "flt-semantic-node-8", "role": "button"},
                "accessibleName": "Continue",
            }
        )

        self.assertEqual(label, "<flt-semantics (Continue)>")

    def test_format_element_label_prefers_aria_label(self):
        label = _format_element_label(
            {
                "tagName": "input",
                "attributes": {"id": "email", "aria-label": "Email"},
                "accessibleName": "Email",
            }
        )

        self.assertEqual(label, '<input aria-label="Email">')

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
        locator = self._unique_locator()
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
        locator = self._unique_locator()
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
        locator = self._unique_locator()
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
