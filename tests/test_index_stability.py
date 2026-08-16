import unittest
from unittest.mock import MagicMock

from smart_automator.actions.builder import _resolve_element_for_action
from smart_automator.actions.schemas import Action
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.page import Page


def _button(index: int, label: str, xpath: str) -> DOMElementNode:
    return DOMElementNode(
        tag_name="button",
        xpath=xpath,
        highlight_index=index,
        attributes={"aria-label": label},
        children=[],
    )


class TestStableIndexResolution(unittest.TestCase):
    def test_resolves_by_xpath_when_highlight_indexes_shift(self):
        original = _button(12, "0", "/body/button[4]")
        # After rebuild, digit 0 moved from index 12 -> 11, and index 12 is now digit 3.
        shifted_zero = _button(11, "0", "/body/button[4]")
        shifted_three = _button(12, "3", "/body/button[1]")
        selector_map = {11: shifted_zero, 12: shifted_three}
        tree = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[shifted_three, shifted_zero],
        )
        action = Action(name="click_element", args={"index": 12})
        resolved = _resolve_element_for_action(
            action,
            selector_map,
            element_tree=tree,
            original_element=original,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.xpath, "/body/button[4]")
        self.assertEqual(resolved.attributes.get("aria-label"), "0")

    def test_locate_prefers_text_match_among_css_duplicates(self):
        page = Page.__new__(Page)
        page._include_dynamic_attributes = True
        page._page = MagicMock()

        zero = _button(12, "0", "/body/button[4]")
        wrong = MagicMock()
        wrong.evaluate.return_value = {
            "aria": "3",
            "placeholder": "",
            "name": "",
            "title": "",
            "alt": "",
            "id": "",
            "testid": "",
            "text": "3",
            "svgTitle": "",
        }
        right = MagicMock()
        right.evaluate.return_value = {
            "aria": "0",
            "placeholder": "",
            "name": "",
            "title": "",
            "alt": "",
            "id": "",
            "testid": "",
            "text": "0",
            "svgTitle": "",
        }

        frame = MagicMock()
        frame.query_selector.return_value = None
        frame.query_selector_all.return_value = [wrong, right]

        handle = page._query_unique_handle(frame, zero)
        self.assertIs(handle, right)


if __name__ == "__main__":
    unittest.main()
