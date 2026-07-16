import unittest
from unittest.mock import MagicMock, patch

from smart_automator.actions.builder import _action_will_navigate
from smart_automator.actions.schemas import Action
from smart_automator.browser.dom import DOMElementNode, DOMState
from smart_automator.browser.page import Page


def _dom_state(
    *,
    button_xpath: str = "/body/button[1]",
    extra_node: DOMElementNode | None = None,
) -> DOMState:
    node = DOMElementNode(
        tag_name="button",
        xpath=button_xpath,
        highlight_index=0,
        attributes={"aria-label": "Submit"},
    )
    children = [node]
    selector_map = {0: node}
    if extra_node is not None:
        children.append(extra_node)
        selector_map[extra_node.highlight_index] = extra_node
    tree = DOMElementNode(tag_name="body", xpath="/body", children=children)
    return DOMState(element_tree=tree, selector_map=selector_map)


class TestActionWillNavigate(unittest.TestCase):
    def test_go_to_url_same_path_skips(self):
        action = Action(name="go_to_url", args={"url": "https://example.com/"})
        self.assertFalse(_action_will_navigate(action, "https://example.com"))

    def test_go_to_url_different_path_navigates(self):
        action = Action(name="go_to_url", args={"url": "https://example.com/other"})
        self.assertTrue(_action_will_navigate(action, "https://example.com"))

    def test_go_back_navigates(self):
        action = Action(name="go_back", args={})
        self.assertTrue(_action_will_navigate(action, "https://example.com"))


class TestGetDomStateHighlightStability(unittest.TestCase):
    def test_skips_redraw_when_signature_unchanged(self):
        page = Page.__new__(Page)
        page._page = MagicMock()
        page._viewport_expansion = 0
        page._selector_map = {}
        page._cached_state = None
        dom_state = _dom_state()
        signature = ("https://example.com", "Example", frozenset({"button:/body/button[1]"}))
        page._last_highlight_signature = signature

        with (
            patch.object(page, "wait_for_page_stable"),
            patch.object(page, "url", return_value=signature[0]),
            patch.object(page, "title", return_value=signature[1]),
            patch.object(page, "_highlights_visible", return_value=True),
            patch("smart_automator.browser.page.build_dom_tree", return_value=dom_state) as build_dom_tree,
            patch("smart_automator.browser.page.remove_highlights") as remove_highlights,
        ):
            result = page.get_dom_state(show_highlights=True)

        self.assertIs(result, dom_state)
        build_dom_tree.assert_called_once()
        build_dom_tree.assert_called_with(
            page._page,
            show_highlights=True,
            focus_element=-1,
            viewport_expansion=0,
            do_highlight_elements=False,
        )
        remove_highlights.assert_not_called()

    def test_redraws_when_branch_hashes_shrink(self):
        page = Page.__new__(Page)
        page._page = MagicMock()
        page._viewport_expansion = 0
        page._selector_map = {}
        page._cached_state = None
        dom_state = _dom_state()
        page._last_highlight_signature = (
            "https://example.com",
            "Example",
            frozenset({"button:/body/button[1]", "button:/body/button[2]"}),
        )

        with (
            patch.object(page, "wait_for_page_stable"),
            patch.object(page, "url", return_value="https://example.com"),
            patch.object(page, "title", return_value="Example"),
            patch.object(page, "_highlights_visible", return_value=True),
            patch(
                "smart_automator.browser.page.build_dom_tree",
                side_effect=[dom_state, dom_state],
            ) as build_dom_tree,
            patch("smart_automator.browser.page.remove_highlights") as remove_highlights,
        ):
            result = page.get_dom_state(show_highlights=True)

        self.assertIs(result, dom_state)
        self.assertEqual(build_dom_tree.call_count, 2)
        remove_highlights.assert_called_once_with(page._page)

    def test_redraws_when_new_interactive_elements_appear(self):
        page = Page.__new__(Page)
        page._page = MagicMock()
        page._viewport_expansion = 0
        page._selector_map = {}
        page._cached_state = None
        extra = DOMElementNode(
            tag_name="button",
            xpath="/body/button[2]",
            highlight_index=1,
            attributes={"aria-label": "Cancel"},
        )
        dom_state = _dom_state(extra_node=extra)
        page._last_highlight_signature = (
            "https://example.com",
            "Example",
            frozenset({"button:/body/button[1]"}),
        )

        with (
            patch.object(page, "wait_for_page_stable"),
            patch.object(page, "url", return_value="https://example.com"),
            patch.object(page, "title", return_value="Example"),
            patch.object(page, "_highlights_visible", return_value=True),
            patch(
                "smart_automator.browser.page.build_dom_tree",
                side_effect=[dom_state, dom_state],
            ) as build_dom_tree,
            patch("smart_automator.browser.page.remove_highlights") as remove_highlights,
        ):
            result = page.get_dom_state(show_highlights=True)

        self.assertIs(result, dom_state)
        self.assertEqual(build_dom_tree.call_count, 2)
        remove_highlights.assert_called_once_with(page._page)

    def test_redraws_when_signature_changed(self):
        page = Page.__new__(Page)
        page._page = MagicMock()
        page._viewport_expansion = 0
        page._selector_map = {}
        page._cached_state = None
        dom_state = _dom_state()
        page._last_highlight_signature = (
            "https://example.com",
            "Old title",
            frozenset({"button:/body/button[1]"}),
        )

        with (
            patch.object(page, "wait_for_page_stable"),
            patch.object(page, "url", return_value="https://example.com"),
            patch.object(page, "title", return_value="Example"),
            patch.object(page, "_highlights_visible", return_value=True),
            patch(
                "smart_automator.browser.page.build_dom_tree",
                side_effect=[dom_state, dom_state],
            ) as build_dom_tree,
            patch("smart_automator.browser.page.remove_highlights") as remove_highlights,
        ):
            result = page.get_dom_state(show_highlights=True)

        self.assertIs(result, dom_state)
        self.assertEqual(build_dom_tree.call_count, 2)
        remove_highlights.assert_called_once_with(page._page)
        self.assertEqual(page._last_highlight_signature[1], "Example")

    def test_probe_only_snapshot_does_not_remove_highlights(self):
        page = Page.__new__(Page)
        page._page = MagicMock()
        page._viewport_expansion = 0
        page._selector_map = {}
        page._cached_state = None
        dom_state = _dom_state()
        page._last_highlight_signature = (
            "https://example.com",
            "Example",
            frozenset({"button:/body/button[1]"}),
        )

        with (
            patch.object(page, "wait_for_page_stable"),
            patch.object(page, "url", return_value="https://example.com"),
            patch.object(page, "title", return_value="Changed title"),
            patch.object(page, "_highlights_visible", return_value=True),
            patch("smart_automator.browser.page.build_dom_tree", return_value=dom_state) as build_dom_tree,
            patch("smart_automator.browser.page.remove_highlights") as remove_highlights,
        ):
            result = page.get_dom_state(show_highlights=False)

        self.assertIs(result, dom_state)
        build_dom_tree.assert_called_once()
        remove_highlights.assert_not_called()
        self.assertEqual(page._last_highlight_signature[1], "Example")


if __name__ == "__main__":
    unittest.main()
