import unittest
from unittest.mock import MagicMock

from smart_automator.browser.dom import DOMElementNode, DOMTextNode
from smart_automator.browser.history import (
    convert_dom_element_to_history_element,
    resolve_history_element_in_tree,
)
from smart_automator.browser.locators import (
    JS_CLICK_JS,
    ReplayLocatorError,
    click_with_fallback,
    duplicate_set_selector,
    identity_values_equal,
    inferred_role,
    is_hashed_css_class,
    is_unstable_id,
    relative_xpath,
    resolve_replay_locator,
    split_locator_candidates,
)


def _unlabeled_buttons(count: int) -> tuple[DOMElementNode, list[DOMElementNode]]:
    body = DOMElementNode(tag_name="body", xpath="html/body")
    wrappers: list[DOMElementNode] = []
    buttons: list[DOMElementNode] = []
    for index in range(count):
        wrap = DOMElementNode(
            tag_name="div",
            xpath=f"html/body/div[{index + 1}]",
            parent=body,
        )
        button = DOMElementNode(
            tag_name="button",
            xpath=f"html/body/div[{index + 1}]/button",
            highlight_index=index + 1,
            parent=wrap,
        )
        wrap.children = [button]
        wrappers.append(wrap)
        buttons.append(button)
    body.children = wrappers
    return body, buttons


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

    def test_duplicate_set_selector_is_tag_or_role_only(self):
        self.assertEqual(duplicate_set_selector("button"), "button")
        self.assertEqual(duplicate_set_selector("button", role="button"), "button")
        self.assertEqual(duplicate_set_selector("div", role="button"), 'div[role="button"]')
        self.assertNotIn(".", duplicate_set_selector("button"))
        self.assertNotIn(".", duplicate_set_selector("div", role="button"))

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
        self.assertEqual(payload["locatorChain"][0]["kind"], "relative")
        self.assertEqual(payload["locatorChain"][0]["root"], "#login-form")

    def test_duplicate_close_records_scoped_relative_chain(self):
        body = DOMElementNode(tag_name="body", xpath="html/body")
        dialog = DOMElementNode(
            tag_name="dialog",
            xpath="html/body/dialog",
            attributes={"id": "confirm"},
            parent=body,
        )
        header = DOMElementNode(tag_name="header", xpath="html/body/header", parent=body)
        dialog_close = DOMElementNode(
            tag_name="button",
            xpath="html/body/dialog/button[1]",
            attributes={"aria-label": "Close"},
            highlight_index=1,
            parent=dialog,
        )
        header_close = DOMElementNode(
            tag_name="button",
            xpath="html/body/header/button[1]",
            attributes={"aria-label": "Close"},
            highlight_index=2,
            parent=header,
        )
        body.children = [dialog, header]
        dialog.children = [dialog_close]
        header.children = [header_close]

        history = convert_dom_element_to_history_element(dialog_close)
        self.assertEqual(history.locator_chain[0]["kind"], "relative")
        self.assertEqual(history.locator_chain[0]["root"], "#confirm")
        identity, _positional = split_locator_candidates({"element": history.to_dict(), "args": {}})
        self.assertEqual(identity[0][0], "relative")
        self.assertFalse(any(kind == "label" for kind, _ in identity))

        remapped = resolve_history_element_in_tree(history, body)
        self.assertIs(remapped, dialog_close)

    def test_unlabeled_twins_record_duplicate_set_count(self):
        body = DOMElementNode(tag_name="body", xpath="html/body")
        left = DOMElementNode(tag_name="div", xpath="html/body/div[1]", parent=body)
        right = DOMElementNode(tag_name="div", xpath="html/body/div[2]", parent=body)
        first = DOMElementNode(
            tag_name="button",
            xpath="html/body/div[1]/button",
            highlight_index=1,
            parent=left,
        )
        second = DOMElementNode(
            tag_name="button",
            xpath="html/body/div[2]/button",
            highlight_index=2,
            parent=right,
        )
        body.children = [left, right]
        left.children = [first]
        right.children = [second]

        history = convert_dom_element_to_history_element(first)
        nth = history.locator_chain[0]
        self.assertEqual(nth["kind"], "first")
        self.assertEqual(nth["selector"], "button")
        self.assertNotIn(".", nth["selector"])
        self.assertEqual(history.duplicate_set["index"], 1)
        self.assertEqual(history.duplicate_set["count"], 2)
        self.assertEqual(history.duplicate_set["position"], "first")
        self.assertEqual(nth["parentTag"], "div")
        self.assertEqual(nth["siblingCount"], 1)
        self.assertEqual(nth["prevTag"], "")
        self.assertEqual(nth["nextTag"], "")

        remapped = resolve_history_element_in_tree(history, body)
        self.assertIs(remapped, first)

        left.children = []
        missed = resolve_history_element_in_tree(history, body)
        self.assertIsNone(missed)

    def test_unlabeled_singleton_records_nth_count_one(self):
        body = DOMElementNode(tag_name="body", xpath="html/body")
        button = DOMElementNode(
            tag_name="button",
            xpath="html/body/button",
            attributes={"class": "primary-button css-1a2b3c"},
            highlight_index=1,
            parent=body,
        )
        body.children = [button]

        history = convert_dom_element_to_history_element(button)
        self.assertTrue(history.locator_chain)
        nth = history.locator_chain[0]
        self.assertEqual(nth["kind"], "nth")
        self.assertEqual(nth["selector"], "button")
        self.assertNotIn(".", nth["selector"])
        self.assertEqual(nth["index"], 1)
        self.assertEqual(nth["count"], 1)
        self.assertEqual(nth["parentTag"], "body")
        self.assertEqual(nth["siblingCount"], 1)
        self.assertEqual(nth["prevTag"], "")
        self.assertEqual(nth["nextTag"], "")
        self.assertEqual(history.duplicate_set["count"], 1)

        remapped = resolve_history_element_in_tree(history, body)
        self.assertIs(remapped, button)

    def test_nth_misses_when_neighbors_change(self):
        body, buttons = _unlabeled_buttons(3)
        middle = buttons[1]
        history = convert_dom_element_to_history_element(middle)
        self.assertEqual(history.locator_chain[0]["kind"], "nth")
        self.assertEqual(history.locator_chain[0]["index"], 2)
        extra = DOMElementNode(
            tag_name="span",
            xpath="html/body/div[2]/span",
            parent=middle.parent,
        )
        middle.parent.children = [middle, extra]
        missed = resolve_history_element_in_tree(history, body)
        self.assertIsNone(missed)

    def test_last_of_three_follows_growth(self):
        body, buttons = _unlabeled_buttons(3)
        history = convert_dom_element_to_history_element(buttons[2])
        last = history.locator_chain[0]
        self.assertEqual(last["kind"], "last")
        self.assertEqual(last["selector"], "button")
        self.assertNotIn(".", last["selector"])
        self.assertEqual(last["count"], 3)
        self.assertEqual(history.duplicate_set["position"], "last")

        remapped = resolve_history_element_in_tree(history, body)
        self.assertIs(remapped, buttons[2])

        fourth_wrap = DOMElementNode(tag_name="div", xpath="html/body/div[4]", parent=body)
        fourth = DOMElementNode(
            tag_name="button",
            xpath="html/body/div[4]/button",
            highlight_index=4,
            parent=fourth_wrap,
        )
        fourth_wrap.children = [fourth]
        body.children = list(body.children) + [fourth_wrap]
        grown = resolve_history_element_in_tree(history, body)
        self.assertIs(grown, fourth)

    def test_first_of_three_follows_growth(self):
        body, buttons = _unlabeled_buttons(3)
        history = convert_dom_element_to_history_element(buttons[0])
        self.assertEqual(history.locator_chain[0]["kind"], "first")
        fourth_wrap = DOMElementNode(tag_name="div", xpath="html/body/div[4]", parent=body)
        fourth = DOMElementNode(
            tag_name="button",
            xpath="html/body/div[4]/button",
            highlight_index=4,
            parent=fourth_wrap,
        )
        fourth_wrap.children = [fourth]
        body.children = list(body.children) + [fourth_wrap]
        remapped = resolve_history_element_in_tree(history, body)
        self.assertIs(remapped, buttons[0])

    def test_middle_nth_keeps_index_when_set_grows(self):
        body, buttons = _unlabeled_buttons(3)
        history = convert_dom_element_to_history_element(buttons[1])
        self.assertEqual(history.locator_chain[0]["kind"], "nth")
        self.assertEqual(history.locator_chain[0]["index"], 2)
        fourth_wrap = DOMElementNode(tag_name="div", xpath="html/body/div[4]", parent=body)
        fourth = DOMElementNode(
            tag_name="button",
            xpath="html/body/div[4]/button",
            highlight_index=4,
            parent=fourth_wrap,
        )
        fourth_wrap.children = [fourth]
        body.children = list(body.children) + [fourth_wrap]
        remapped = resolve_history_element_in_tree(history, body)
        self.assertIs(remapped, buttons[1])

    def test_singleton_nth_misses_when_extra_sibling_changes_neighbors(self):
        body = DOMElementNode(tag_name="body", xpath="html/body")
        button = DOMElementNode(
            tag_name="button",
            xpath="html/body/button",
            highlight_index=1,
            parent=body,
        )
        body.children = [button]
        history = convert_dom_element_to_history_element(button)
        self.assertEqual(history.locator_chain[0]["kind"], "nth")
        self.assertEqual(history.locator_chain[0]["count"], 1)
        extra = DOMElementNode(
            tag_name="button",
            xpath="html/body/button[2]",
            highlight_index=2,
            parent=body,
        )
        body.children = [button, extra]
        missed = resolve_history_element_in_tree(history, body)
        self.assertIsNone(missed)

    def test_nested_svg_title_is_identity(self):
        body = DOMElementNode(tag_name="body", xpath="html/body")
        button = DOMElementNode(
            tag_name="button",
            xpath="html/body/button",
            highlight_index=1,
            parent=body,
        )
        svg = DOMElementNode(tag_name="svg", xpath="html/body/button/svg", parent=button)
        title = DOMElementNode(tag_name="title", xpath="html/body/button/svg/title", parent=svg)
        title.children = [DOMTextNode(text="Save")]
        svg.children = [title]
        button.children = [svg]
        body.children = [button]

        history = convert_dom_element_to_history_element(button)
        self.assertEqual(history.nested_identity, "Save")
        kind = history.locator_chain[0]["kind"]
        self.assertIn(kind, {"text", "role"})
        if kind == "role":
            self.assertEqual(history.locator_chain[0]["name"], "Save")
        else:
            self.assertEqual(history.locator_chain[0]["text"], "Save")

    def test_flutter_id_is_not_capture_identity(self):
        body = DOMElementNode(tag_name="body", xpath="html/body")
        button = DOMElementNode(
            tag_name="flt-semantics",
            xpath="html/body/flt-semantics",
            attributes={"id": "flt-semantic-node-8", "role": "button"},
            highlight_index=1,
            parent=body,
        )
        body.children = [button]
        history = convert_dom_element_to_history_element(button)
        kinds = [item["kind"] for item in history.locator_chain]
        self.assertNotIn("css", kinds)
        self.assertEqual(kinds[0], "nth")
        payload = history.to_dict()
        selector = payload.get("locatorChain", [{}])[0].get("selector")
        self.assertNotEqual(selector, "#flt-semantic-node-8")
        self.assertNotIn(".", selector or "")
        self.assertEqual(payload["locatorChain"][0]["count"], 1)

    def test_replay_nth_misses_when_count_changes(self):
        page = MagicMock()
        locator = MagicMock()
        visible = MagicMock()
        locator.filter.return_value = visible
        visible.count.return_value = 1
        page.locator.return_value = locator
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "locatorChain": [{
                    "kind": "nth",
                    "selector": "button",
                    "index": 1,
                    "count": 2,
                }],
                "duplicateSet": {"selector": "button", "index": 1, "count": 2},
            },
        }
        with self.assertRaises(ReplayLocatorError):
            resolve_replay_locator(page, step, poll_timeout_seconds=0)

    def test_replay_nth_clicks_recorded_index_when_count_matches(self):
        page = MagicMock()
        locator = MagicMock()
        visible = MagicMock()
        chosen = MagicMock()
        locator.filter.return_value = visible
        visible.count.return_value = 3
        visible.nth.return_value = chosen
        page.locator.return_value = locator
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "locatorChain": [{
                    "kind": "nth",
                    "selector": "button",
                    "index": 2,
                    "count": 3,
                }],
            },
        }
        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)
        self.assertIs(resolved, chosen)
        visible.nth.assert_called_once_with(1)

    def test_replay_legacy_nth_end_uses_last_when_set_grows(self):
        page = MagicMock()
        locator = MagicMock()
        visible = MagicMock()
        chosen = MagicMock()
        locator.filter.return_value = visible
        visible.count.return_value = 4
        visible.last = chosen
        page.locator.return_value = locator
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "locatorChain": [{
                    "kind": "nth",
                    "selector": "button",
                    "index": 3,
                    "count": 3,
                }],
            },
        }
        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)
        self.assertIs(resolved, chosen)

    def test_replay_first_clicks_first_when_set_grows(self):
        page = MagicMock()
        locator = MagicMock()
        visible = MagicMock()
        chosen = MagicMock()
        locator.filter.return_value = visible
        visible.count.return_value = 4
        visible.first = chosen
        page.locator.return_value = locator
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "locatorChain": [{
                    "kind": "first",
                    "selector": "button",
                    "index": 1,
                    "count": 3,
                }],
            },
        }
        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)
        self.assertIs(resolved, chosen)

    def test_replay_nth_clicks_when_neighbors_match(self):
        page = MagicMock()
        locator = MagicMock()
        visible = MagicMock()
        chosen = MagicMock()
        locator.filter.return_value = visible
        visible.count.return_value = 1
        visible.nth.return_value = chosen
        chosen.evaluate.return_value = {
            "parentTag": "body",
            "siblingCount": 1,
            "prevTag": "",
            "nextTag": "",
        }
        page.locator.return_value = locator
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "locatorChain": [{
                    "kind": "nth",
                    "selector": "button",
                    "index": 1,
                    "count": 1,
                    "parentTag": "body",
                    "siblingCount": 1,
                    "prevTag": "",
                    "nextTag": "",
                }],
            },
        }
        resolved = resolve_replay_locator(page, step, poll_timeout_seconds=0)
        self.assertIs(resolved, chosen)

    def test_replay_nth_misses_when_neighbors_disagree(self):
        page = MagicMock()
        locator = MagicMock()
        visible = MagicMock()
        chosen = MagicMock()
        locator.filter.return_value = visible
        visible.count.return_value = 3
        visible.nth.return_value = chosen
        chosen.evaluate.return_value = {
            "parentTag": "section",
            "siblingCount": 3,
            "prevTag": "span",
            "nextTag": "",
        }
        page.locator.return_value = locator
        step = {
            "action": "click_element",
            "args": {},
            "element": {
                "locatorChain": [{
                    "kind": "nth",
                    "selector": "button",
                    "index": 2,
                    "count": 3,
                    "parentTag": "div",
                    "siblingCount": 1,
                    "prevTag": "",
                    "nextTag": "",
                }],
            },
        }
        with self.assertRaises(ReplayLocatorError):
            resolve_replay_locator(page, step, poll_timeout_seconds=0)


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

    def test_destroyed_context_on_js_click_raises(self):
        target = MagicMock()
        target.click.side_effect = TimeoutError("intercepts pointer events")

        def evaluate(script, *args):
            if script == JS_CLICK_JS:
                raise RuntimeError(
                    "Execution context was destroyed, most likely because of a navigation"
                )
            return None

        target.evaluate.side_effect = evaluate
        with self.assertRaises(RuntimeError) as ctx:
            click_with_fallback(target, verify=lambda: None)
        self.assertIn("destroyed", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
