import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import _resolve_element_for_action
from smart_automator.actions.schemas import Action
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.page import Page


def _button(
    index: int,
    label: str,
    xpath: str,
    *,
    parent: DOMElementNode | None = None,
) -> DOMElementNode:
    node = DOMElementNode(
        tag_name="button",
        xpath=xpath,
        highlight_index=index,
        attributes={"aria-label": label},
        children=[],
        parent=parent,
    )
    return node


def _shadow_host(xpath: str, *, parent: DOMElementNode | None = None) -> DOMElementNode:
    return DOMElementNode(
        tag_name="custom-modal",
        xpath=xpath,
        shadow_root=True,
        children=[],
        parent=parent,
    )


class TestLocateElement(unittest.TestCase):
    def setUp(self):
        self.page = Page.__new__(Page)
        self.page._include_dynamic_attributes = True
        self.page._page = MagicMock()
        self.page.wait_for_page_stable = MagicMock()

    def test_format_element_not_found_error_includes_xpath_and_identity(self):
        element = _button(0, "Close", "/body/button[1]")
        message = self.page._format_element_not_found_error(element)
        self.assertIn("index=0", message)
        self.assertIn("xpath=/body/button[1]", message)
        self.assertIn("aria-label='Close'", message)
        self.assertIn("tag=button", message)

    def test_format_element_not_found_error_notes_shadow_dom(self):
        host = _shadow_host("custom-modal[1]")
        close = _button(0, "Close", "button[1]", parent=host)
        host.children = [close]
        message = self.page._format_element_not_found_error(close)
        self.assertIn("inside shadow DOM", message)

    def test_locate_element_pierces_shadow_root(self):
        body = DOMElementNode(tag_name="body", xpath="/body", children=[])
        host = _shadow_host("custom-modal[1]", parent=body)
        close = _button(0, "Close", "button[1]", parent=host)
        host.children = [close]
        body.children = [host]

        host_handle = MagicMock()
        close_handle = MagicMock()
        close_handle.as_element.return_value = close_handle
        host_handle.evaluate_handle.return_value = close_handle
        host_handle.evaluate.return_value = 0

        with patch.object(self.page, "_query_unique_handle", side_effect=[host_handle, close_handle]) as query_mock:
            located = self.page._locate_element(close)

        self.assertIs(located, close_handle)
        self.assertEqual(query_mock.call_count, 2)
        second_call = query_mock.call_args_list[1]
        self.assertEqual(second_call[0][1], close)
        self.assertEqual(second_call[0][2], [host_handle])

    def test_locate_element_with_retry_waits_and_retries(self):
        element = _button(0, "Close", "/body/button[1]")
        with patch.object(self.page, "_locate_element", side_effect=[None, MagicMock()]) as locate:
            handle = self.page._locate_element_with_retry(element)
        self.assertIsNotNone(handle)
        self.assertEqual(locate.call_count, 2)
        self.page.wait_for_page_stable.assert_called_once()

    def test_select_unique_handle_rejects_identity_mismatch(self):
        element = _button(0, "Close", "/body/button[1]")
        handle = MagicMock()
        handle.evaluate.return_value = {
            "aria": "Submit",
            "placeholder": "",
            "name": "",
            "title": "",
            "alt": "",
            "id": "",
            "testid": "",
            "text": "Submit",
            "svgTitle": "",
        }
        matched = self.page._select_unique_handle([handle], element)
        self.assertIsNone(matched)

    def test_select_unique_handle_accepts_exact_aria(self):
        element = _button(0, "Close", "/body/button[1]")
        handle = MagicMock()
        handle.evaluate.return_value = {
            "aria": "Close",
            "placeholder": "",
            "name": "",
            "title": "",
            "alt": "",
            "id": "",
            "testid": "",
            "text": "Close",
            "svgTitle": "",
        }
        matched = self.page._select_unique_handle([handle], element)
        self.assertIs(matched, handle)


class TestRemapFallback(unittest.TestCase):
    def test_falls_back_to_current_selector_map_when_original_xpath_gone(self):
        stale = _button(0, "Close", "/body/button[9]")
        current = _button(0, "Close", "/body/button[1]")
        selector_map = {0: current}
        tree = DOMElementNode(tag_name="body", xpath="/body", children=[current])
        action = Action(name="click_element", args={"index": 0})

        resolved = _resolve_element_for_action(
            action,
            selector_map,
            element_tree=tree,
            original_element=stale,
        )

        self.assertIs(resolved, current)
        self.assertEqual(resolved.xpath, "/body/button[1]")

    def test_does_not_fall_back_to_neighbor_at_same_index(self):
        stale = _button(0, "Close", "/body/button[9]")
        neighbor = _button(0, "Submit", "/body/button[1]")
        selector_map = {0: neighbor}
        tree = DOMElementNode(tag_name="body", xpath="/body", children=[neighbor])
        action = Action(name="click_element", args={"index": 0})

        resolved = _resolve_element_for_action(
            action,
            selector_map,
            element_tree=tree,
            original_element=stale,
        )

        self.assertIsNone(resolved)

    def test_returns_none_when_original_and_map_miss(self):
        stale = _button(0, "Close", "/body/button[9]")
        selector_map: dict[int, DOMElementNode] = {}
        tree = DOMElementNode(tag_name="body", xpath="/body", children=[])
        action = Action(name="click_element", args={"index": 0})

        resolved = _resolve_element_for_action(
            action,
            selector_map,
            element_tree=tree,
            original_element=stale,
        )

        self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
