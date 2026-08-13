"""Tests for saved replay step execution."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.reporting.replay_executor import (
    _resolve_locator,
    execute_replay_steps,
)
from smart_automator.reporting.replay_script import (
    ReplayLocatorError,
    _format_element_label,
    _playwright_locator,
    _sanitize_css_for_flutter,
    assert_locator_matches_identity,
    resolve_replay_locator,
)


class TestReplayExecutor(unittest.TestCase):
    @staticmethod
    def _unique_locator() -> MagicMock:
        locator = MagicMock()
        locator.count.return_value = 1
        locator.evaluate.return_value = {
            "aria": "",
            "placeholder": "",
            "name": "",
            "title": "",
            "id": "",
            "testid": "",
            "text": "",
        }
        return locator

    @staticmethod
    def _ambiguous_locator_with_unique_leaf() -> MagicMock:
        locator = MagicMock()
        locator.count.return_value = 2
        leaf = MagicMock()
        leaf.count.return_value = 1
        locator.locator.return_value = leaf
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

        _resolve_locator(page, step, poll_timeout_seconds=0)

        page.get_by_label.assert_called_once_with("Abdul Bassit", exact=True)

    def test_resolve_locator_uses_id_without_label(self):
        page = MagicMock()
        page.locator.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {},
            "element": {"attributes": {"id": "submit-btn"}},
        }

        _resolve_locator(page, step, poll_timeout_seconds=0)

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

        _resolve_locator(page, step, poll_timeout_seconds=0)

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

        resolved = _resolve_locator(page, step, poll_timeout_seconds=0)

        page.get_by_role.assert_called_once_with("button", name="Continue", exact=True)
        page.locator.assert_not_called()
        self.assertIs(resolved, page.get_by_role.return_value)

    def test_resolve_locator_narrows_ambiguous_label_to_editable_leaf(self):
        page = MagicMock()
        page.get_by_label.return_value = self._ambiguous_locator_with_unique_leaf()
        step = {
            "action": "input_text",
            "args": {
                "text": "user@example.com",
                "xpath": "html/body/flt-semantics[2]/input",
                "css_selector": (
                    'flt-semantics:nth-of-type(2) > input[aria-label="Email"]'
                ),
            },
            "element": {
                "attributes": {"aria-label": "Email", "type": "text"},
            },
        }

        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)

        page.get_by_label.assert_called_once_with("Email", exact=True)
        page.get_by_label.return_value.locator.assert_called_once()
        self.assertIs(resolved, page.get_by_label.return_value.locator.return_value)
        page.locator.assert_not_called()

    def test_resolve_locator_refuses_positional_fallback_when_identity_recorded(self):
        page = MagicMock()
        ambiguous = MagicMock()
        ambiguous.count.return_value = 2
        leaf = MagicMock()
        leaf.count.return_value = 0
        ambiguous.locator.return_value = leaf
        page.get_by_role.return_value = ambiguous
        page.locator.return_value = self._unique_locator()
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

        with self.assertRaises(ReplayLocatorError) as ctx:
            resolve_replay_locator(page, step, poll_timeout_seconds=0)

        self.assertIn("recorded identity", str(ctx.exception))
        page.locator.assert_not_called()

    def test_resolve_locator_falls_back_when_role_is_ambiguous(self):
        # Kept name for compatibility: accessible-name identity must not use positional CSS.
        page = MagicMock()
        role_locator = MagicMock()
        role_locator.count.return_value = 2
        role_locator.locator.return_value.count.return_value = 0
        page.get_by_role.return_value = role_locator
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

        with self.assertRaises(ReplayLocatorError):
            _resolve_locator(page, step, poll_timeout_seconds=0)

        page.get_by_role.assert_called_once_with("button", name="Meals", exact=True)
        page.locator.assert_not_called()

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

    def test_identity_gate_accepts_matching_aria_label(self):
        locator = MagicMock()
        locator.evaluate.return_value = {
            "aria": "Email",
            "placeholder": "",
            "name": "",
            "title": "",
            "text": "",
        }
        step = {
            "element": {"attributes": {"aria-label": "Email"}},
        }

        assert_locator_matches_identity(locator, step)

    def test_identity_gate_rejects_neighbor_aria_label(self):
        locator = MagicMock()
        locator.evaluate.return_value = {
            "aria": "Password",
            "placeholder": "",
            "name": "",
            "title": "",
            "text": "",
        }
        step = {
            "element": {"attributes": {"aria-label": "Email"}},
        }

        with self.assertRaises(ReplayLocatorError) as ctx:
            assert_locator_matches_identity(locator, step)

        self.assertIn("Password", str(ctx.exception))
        self.assertIn("Email", str(ctx.exception))

    def test_settle_wait_after_successful_click(self):
        browser_context = MagicMock()
        page_wrapper = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        locator.evaluate.return_value["id"] = "submit-btn"
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
        locator.evaluate.return_value["id"] = "submit-btn"
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

    def test_execute_input_errors_on_identity_mismatch(self):
        browser_context = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        locator.evaluate.return_value = {
            "aria": "Password",
            "placeholder": "",
            "name": "",
            "title": "",
            "text": "",
        }
        page.get_by_label.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "input_text",
                "args": {"text": "user@example.com"},
                "element": {"attributes": {"aria-label": "Email"}},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        locator.fill.assert_not_called()
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("Password", results[0].error or "")

    @patch("smart_automator.reporting.replay_executor.time.sleep")
    def test_retries_failed_step_after_wait(self, mock_sleep):
        browser_context = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        locator.evaluate.return_value["id"] = "btn"

        def evaluate(script, *args):
            if script == "el => el.click()":
                raise RuntimeError("js click failed")
            return locator.evaluate.return_value

        locator.evaluate.side_effect = evaluate
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

    def test_click_falls_back_to_js_click_on_intercept(self):
        browser_context = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        locator.evaluate.return_value["id"] = "submit-btn"
        locator.click.side_effect = TimeoutError(
            "Locator.click: Timeout 5000ms exceeded. Default Menu intercepts pointer events"
        )
        page.locator.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "click_element",
                "args": {},
                "element": {"attributes": {"id": "submit-btn"}},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)
        self.assertIn(
            "el => el.click()",
            [call.args[0] for call in locator.evaluate.call_args_list],
        )

    def test_click_does_not_js_fallback_when_detached(self):
        browser_context = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        locator.evaluate.return_value["id"] = "submit-btn"
        locator.click.side_effect = RuntimeError("Element is not attached to the DOM")
        page.locator.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "click_element",
                "args": {},
                "element": {"attributes": {"id": "submit-btn"}},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("not attached", (results[0].error or "").lower())
        self.assertNotIn(
            "el => el.click()",
            [call.args[0] for call in locator.evaluate.call_args_list],
        )

    def test_click_does_not_js_fallback_when_identity_changes(self):
        browser_context = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        matching = {
            "aria": "",
            "placeholder": "",
            "name": "",
            "title": "",
            "id": "submit-btn",
            "testid": "",
            "text": "",
        }
        mismatched = dict(matching, id="other-btn")
        identity_checks = {"count": 0}

        def evaluate(script, *args):
            if "getAttribute" in script:
                identity_checks["count"] += 1
                if identity_checks["count"] == 1:
                    return matching
                return mismatched
            return None

        locator.evaluate.side_effect = evaluate
        locator.click.side_effect = TimeoutError("intercepts pointer events")
        page.locator.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "click_element",
                "args": {},
                "element": {"attributes": {"id": "submit-btn"}},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("intercepts pointer events", results[0].error or "")
        self.assertNotIn(
            "el => el.click()",
            [call.args[0] for call in locator.evaluate.call_args_list],
        )

    def test_locatoreless_scroll_to_percent_uses_window(self):
        browser_context = MagicMock()
        page = MagicMock()
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "scroll_to_percent",
                "args": {"percent": 50, "yPercent": 50},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        page.evaluate.assert_called_once()
        self.assertIn("window.scrollTo", page.evaluate.call_args[0][0])
        self.assertEqual(page.evaluate.call_args[0][1], 50)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)
        self.assertIn("50%", results[0].extracted_content or "")

    def test_scroll_to_percent_with_xpath_uses_element(self):
        browser_context = MagicMock()
        page = MagicMock()
        locator = self._unique_locator()
        page.locator.return_value = locator
        browser_context.get_current_page.return_value.playwright_page = page

        steps = [
            {
                "action": "scroll_to_percent",
                "args": {"percent": 75, "xpath": "html/body/div"},
            }
        ]

        results = execute_replay_steps(browser_context, steps)

        page.locator.assert_called()
        locator.evaluate.assert_called_once()
        self.assertEqual(locator.evaluate.call_args[0][1], 75)
        page.evaluate.assert_not_called()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)

    def test_identity_gate_rejects_substring_accessible_name(self):
        locator = MagicMock()
        locator.evaluate.return_value = {
            "aria": "",
            "placeholder": "",
            "name": "",
            "title": "",
            "text": "OK, continue",
        }
        step = {
            "element": {"accessibleName": "OK"},
        }

        with self.assertRaises(ReplayLocatorError) as ctx:
            assert_locator_matches_identity(locator, step)

        self.assertIn("OK", str(ctx.exception))

    def test_resolve_locator_uses_implicit_button_role(self):
        page = MagicMock()
        page.get_by_role.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "tagName": "button",
                "accessibleName": "Continue",
                "attributes": {},
            },
        }

        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)

        page.get_by_role.assert_called_once_with("button", name="Continue", exact=True)
        self.assertIs(resolved, page.get_by_role.return_value)

    def test_resolve_locator_skips_react_use_id(self):
        page = MagicMock()
        page.locator.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {"xpath": "/html/body/button[1]"},
            "element": {"attributes": {"id": ":r1:"}},
        }

        resolve_replay_locator(page, step, poll_timeout_seconds=0)

        page.locator.assert_called()
        self.assertNotEqual(page.locator.call_args[0][0], "#:r1:")

    def test_resolve_locator_prefers_visible_match(self):
        page = MagicMock()
        ambiguous = MagicMock()
        ambiguous.count.return_value = 2
        visible = self._unique_locator()
        ambiguous.filter.return_value = visible
        page.get_by_label.return_value = ambiguous
        step = {
            "action": "click_element",
            "args": {},
            "element": {"attributes": {"aria-label": "Menu"}},
        }

        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)

        ambiguous.filter.assert_called_with(visible=True)
        self.assertIs(resolved, visible)

    def test_resolve_locator_uses_frame_path(self):
        page = MagicMock()
        frame = MagicMock()
        page.frame_locator.return_value = frame
        frame.get_by_label.return_value = self._unique_locator()
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "attributes": {"aria-label": "Email"},
                "framePath": ["iframe#app"],
            },
        }

        resolve_replay_locator(page, step, poll_timeout_seconds=0)

        page.frame_locator.assert_called_once_with("iframe#app")
        frame.get_by_label.assert_called_once_with("Email", exact=True)


if __name__ == "__main__":
    unittest.main()
