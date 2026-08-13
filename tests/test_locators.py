import unittest
from unittest.mock import MagicMock

from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.history import convert_dom_element_to_history_element
from smart_automator.browser.locators import (
    JS_CLICK_JS,
    click_with_fallback,
    identity_values_equal,
    inferred_role,
    is_hashed_css_class,
    is_unstable_id,
    relative_xpath,
)


class TestLocatorHelpers(unittest.TestCase):
    def test_unstable_ids(self):
        self.assertTrue(is_unstable_id("flt-semantic-node-8"))
        self.assertTrue(is_unstable_id(":r1:"))
        self.assertTrue(is_unstable_id("mui-12"))
        self.assertTrue(is_unstable_id("ember99"))
        self.assertTrue(is_unstable_id("550e8400-e29b-41d4-a716-446655440000"))
        self.assertFalse(is_unstable_id("submit-btn"))
        self.assertFalse(is_unstable_id("email"))

    def test_hashed_css_classes(self):
        self.assertTrue(is_hashed_css_class("css-1a2b3c"))
        self.assertTrue(is_hashed_css_class("sc-bdVaJa"))
        self.assertFalse(is_hashed_css_class("primary-button"))

    def test_inferred_roles(self):
        self.assertEqual(inferred_role("button", {}), "button")
        self.assertEqual(inferred_role("a", {}), "link")
        self.assertEqual(inferred_role("input", {"type": "email"}), "textbox")
        self.assertEqual(inferred_role("input", {"type": "checkbox"}), "checkbox")
        self.assertEqual(inferred_role("div", {"role": "button"}), "button")

    def test_identity_values_equal_normalizes_whitespace(self):
        self.assertTrue(identity_values_equal("Email", " Email "))
        self.assertFalse(identity_values_equal("OK", "OK, continue"))

    def test_relative_xpath(self):
        self.assertEqual(
            relative_xpath("html/body/form", "html/body/form/input[1]"),
            "./input[1]",
        )

    def test_css_selector_omits_hashed_classes_and_unstable_ids(self):
        node = DOMElementNode(
            tag_name="button",
            xpath="html/body/button[1]",
            attributes={
                "class": "css-1a2b3c primary-button",
                "id": "flt-semantic-node-8",
                "aria-label": "Go",
            },
        )
        css = node.enhanced_css_selector_for_element()
        self.assertNotIn("css-1a2b3c", css)
        self.assertNotIn("primary-button", css)
        self.assertNotIn("flt-semantic-node-8", css)
        self.assertIn('aria-label="Go"', css)

    def test_history_capture_records_frame_and_stable_root(self):
        form = DOMElementNode(
            tag_name="form",
            xpath="html/body/form",
            attributes={"id": "login-form"},
        )
        iframe = DOMElementNode(tag_name="iframe", xpath="html/body/iframe[1]")
        button = DOMElementNode(
            tag_name="button",
            xpath="html/body/form/button[1]",
            attributes={"type": "submit"},
            highlight_index=1,
        )
        iframe.parent = None
        form.parent = iframe
        button.parent = form
        form.children = [button]
        iframe.children = [form]

        history = convert_dom_element_to_history_element(button)
        self.assertEqual(history.frame_path, ["html/body/iframe[1]"])
        self.assertEqual(history.stable_root, "#login-form")
        self.assertEqual(history.relative_xpath, "./button[1]")
        payload = history.to_dict()
        self.assertEqual(payload["inferredRole"], "button")


class TestClickWithFallback(unittest.TestCase):
    def test_successful_playwright_click_skips_js_click(self):
        target = MagicMock()
        click_with_fallback(target)
        target.click.assert_called_once()
        js_calls = [
            call for call in target.evaluate.call_args_list if call.args[0] == JS_CLICK_JS
        ]
        self.assertEqual(js_calls, [])

    def test_intercept_with_passing_verify_uses_js_click(self):
        target = MagicMock()
        target.click.side_effect = TimeoutError(
            'Locator.click: Timeout 5000ms exceeded. <div>Default Menu</div> intercepts pointer events'
        )
        click_with_fallback(target, verify=lambda: None)
        js_calls = [
            call for call in target.evaluate.call_args_list if call.args[0] == JS_CLICK_JS
        ]
        self.assertEqual(len(js_calls), 1)

    def test_intercept_with_failing_verify_does_not_js_click(self):
        target = MagicMock()
        original = TimeoutError("intercepts pointer events")
        target.click.side_effect = original

        def fail_verify() -> None:
            raise LookupError("mismatch")

        with self.assertRaises(TimeoutError) as ctx:
            click_with_fallback(target, verify=fail_verify)
        self.assertIs(ctx.exception, original)
        js_calls = [
            call for call in target.evaluate.call_args_list if call.args[0] == JS_CLICK_JS
        ]
        self.assertEqual(js_calls, [])

    def test_detached_error_does_not_js_click(self):
        target = MagicMock()
        target.click.side_effect = RuntimeError("Element is not attached to the DOM")
        with self.assertRaises(RuntimeError):
            click_with_fallback(target, verify=lambda: None)
        js_calls = [
            call for call in target.evaluate.call_args_list if call.args[0] == JS_CLICK_JS
        ]
        self.assertEqual(js_calls, [])

    def test_target_closed_error_does_not_js_click(self):
        target = MagicMock()
        target.click.side_effect = RuntimeError("Target closed")
        with self.assertRaises(RuntimeError):
            click_with_fallback(target, verify=lambda: None)
        js_calls = [
            call for call in target.evaluate.call_args_list if call.args[0] == JS_CLICK_JS
        ]
        self.assertEqual(js_calls, [])


if __name__ == "__main__":
    unittest.main()
