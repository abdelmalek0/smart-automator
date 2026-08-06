"""Tests for nested overflow scrolling (site-agnostic)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from smart_automator.actions.schemas import Action
from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions
from smart_automator.agent.verification import (
    VERIFICATION_NO_EFFECT,
    VERIFICATION_VERIFIED,
    PageSnapshot,
    apply_verification,
)
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.views import BrowserState, ScrollRegion
from smart_automator.utils.prompts import build_browser_state_message, get_navigator_system_prompt


class TestScrollRegion(unittest.TestCase):
    def test_percent_and_boundaries(self):
        region = ScrollRegion(
            key="html/body/div",
            kind="container",
            tag="div",
            xpath="html/body/div",
            scroll_top=0,
            client_height=200,
            scroll_height=1000,
        )
        self.assertEqual(region.overflow, 800)
        self.assertTrue(region.at_top)
        self.assertFalse(region.at_bottom)
        self.assertEqual(region.percent, 0)

        bottom = ScrollRegion(
            key="html/body/div",
            kind="container",
            tag="div",
            xpath="html/body/div",
            scroll_top=800,
            client_height=200,
            scroll_height=1000,
        )
        self.assertTrue(bottom.at_bottom)
        self.assertEqual(bottom.percent, 100)


class TestScrollFingerprintVerification(unittest.TestCase):
    def test_container_only_change_is_detected(self):
        before = PageSnapshot(
            url="https://example.com",
            title="T",
            scroll_y=0,
            scroll_fingerprint=(("window", 0), ("html/body/div[1]", 0)),
        )
        after = PageSnapshot(
            url="https://example.com",
            title="T",
            scroll_y=0,
            scroll_fingerprint=(("window", 0), ("html/body/div[1]", 400)),
        )
        self.assertTrue(before.scroll_changed(after))

    def test_window_change_still_detected(self):
        before = PageSnapshot(url="u", title="t", scroll_y=0, scroll_fingerprint=(("window", 0),))
        after = PageSnapshot(url="u", title="t", scroll_y=50, scroll_fingerprint=(("window", 50),))
        self.assertTrue(before.scroll_changed(after))

    def test_verify_action_marks_container_scroll_verified(self):
        before = PageSnapshot(
            url="https://example.com",
            title="T",
            scroll_y=0,
            scroll_fingerprint=(("window", 0), ("pane", 0)),
        )
        after = PageSnapshot(
            url="https://example.com",
            title="T",
            scroll_y=0,
            scroll_fingerprint=(("window", 0), ("pane", 300)),
        )
        result = ActionResult(extracted_content="Scrolled container (div) to bottom")
        verified = apply_verification(
            Action(name="scroll_to_bottom", args={}),
            result,
            before=before,
            after=after,
            before_element=None,
            after_element=None,
        )
        self.assertEqual(verified.verification_status, VERIFICATION_VERIFIED)

    def test_verify_no_effect_when_fingerprint_unchanged(self):
        snap = PageSnapshot(
            url="https://example.com",
            title="T",
            scroll_y=0,
            scroll_fingerprint=(("window", 0), ("pane", 0)),
        )
        result = ActionResult(extracted_content="Scrolled page to 100%")
        verified = apply_verification(
            Action(name="scroll_to_percent", args={"percent": 100}),
            result,
            before=snap,
            after=snap,
            before_element=None,
            after_element=None,
        )
        self.assertEqual(verified.verification_status, VERIFICATION_NO_EFFECT)

    def test_no_scrollable_region_is_verified_boundary(self):
        snap = PageSnapshot(url="u", title="t", scroll_y=0, scroll_fingerprint=(("window", 0),))
        result = ActionResult(extracted_content="No scrollable region found")
        verified = apply_verification(
            Action(name="scroll_to_bottom", args={}),
            result,
            before=snap,
            after=snap,
            before_element=None,
            after_element=None,
        )
        self.assertEqual(verified.verification_status, VERIFICATION_VERIFIED)


class TestScrollObservation(unittest.TestCase):
    def test_state_message_lists_scrollable_regions(self):
        button = DOMElementNode(
            tag_name="button",
            xpath="/button[1]",
            attributes={"aria-label": "Item"},
            highlight_index=0,
            is_in_viewport=True,
            is_visible=True,
            is_interactive=True,
        )
        root = DOMElementNode(tag_name="body", xpath="/body", children=[button])
        region = ScrollRegion(
            key="html/body/div[1]",
            kind="container",
            tag="div",
            xpath="html/body/div[1]",
            scroll_top=0,
            client_height=400,
            scroll_height=2000,
        )
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            element_tree=root,
            selector_map={0: button},
            tabs=[],
            scroll_y=0,
            scroll_height=800,
            visual_viewport_height=800,
            scroll_regions=[
                ScrollRegion(
                    key="window",
                    kind="window",
                    tag="window",
                    xpath="",
                    scroll_top=0,
                    client_height=800,
                    scroll_height=800,
                ),
                region,
            ],
        )
        context = AgentContext(
            task_id="t1",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        message = build_browser_state_message(context, browser_state)
        self.assertIn("[Scrollable regions]", message)
        self.assertIn("html/body/div[1]", message)
        self.assertIn("at top", message)

    def test_navigator_prompt_mentions_overflow_region(self):
        prompt = get_navigator_system_prompt()
        self.assertIn("primary in-viewport overflow region", prompt)


class TestResolveScrollTargetHelpers(unittest.TestCase):
    def test_primary_prefers_window_when_overflowable(self):
        from smart_automator.browser.page import Page

        page = Page.__new__(Page)
        page.get_window_scroll_region = MagicMock(
            return_value=ScrollRegion(
                key="window",
                kind="window",
                tag="window",
                xpath="",
                scroll_top=0,
                client_height=800,
                scroll_height=2400,
            )
        )
        page.discover_scrollable_containers = MagicMock(
            return_value=[
                ScrollRegion(
                    key="pane",
                    kind="container",
                    tag="div",
                    xpath="html/body/div",
                    scroll_top=0,
                    client_height=400,
                    scroll_height=2000,
                )
            ]
        )
        primary = Page.get_primary_scroll_region(page)
        self.assertIsNotNone(primary)
        assert primary is not None
        self.assertEqual(primary.kind, "window")

    def test_primary_uses_largest_container_when_window_fixed(self):
        from smart_automator.browser.page import Page

        page = Page.__new__(Page)
        page.get_window_scroll_region = MagicMock(
            return_value=ScrollRegion(
                key="window",
                kind="window",
                tag="window",
                xpath="",
                scroll_top=0,
                client_height=800,
                scroll_height=800,
            )
        )
        page.discover_scrollable_containers = MagicMock(
            return_value=[
                ScrollRegion(
                    key="small",
                    kind="container",
                    tag="div",
                    xpath="html/body/div[1]",
                    scroll_top=0,
                    client_height=200,
                    scroll_height=400,
                ),
                ScrollRegion(
                    key="large",
                    kind="container",
                    tag="div",
                    xpath="html/body/div[2]",
                    scroll_top=0,
                    client_height=400,
                    scroll_height=2000,
                ),
            ]
        )
        primary = Page.get_primary_scroll_region(page)
        self.assertIsNotNone(primary)
        assert primary is not None
        self.assertEqual(primary.key, "large")

    def test_scroll_to_percent_returns_none_when_no_target(self):
        from smart_automator.browser.page import Page

        page = Page.__new__(Page)
        page.resolve_scroll_target = MagicMock(return_value=None)
        page._cached_state = None
        self.assertIsNone(Page.scroll_to_percent(page, 100))


class TestOptionalScrollIndexCoercion(unittest.TestCase):
    def test_builder_coerces_string_index(self):
        from smart_automator.actions.builder import ActionBuilder

        context = AgentContext(
            task_id="t",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        page = MagicMock()
        region = ScrollRegion(
            key="pane",
            kind="container",
            tag="div",
            xpath="html/body/div",
            scroll_top=0,
            client_height=200,
            scroll_height=1000,
        )
        page.resolve_scroll_target.return_value = (region, MagicMock())
        page.scroll_to_percent.return_value = region
        context.browser_context.get_current_page.return_value = page

        node = DOMElementNode(
            tag_name="button",
            xpath="/button[1]",
            highlight_index=3,
            is_in_viewport=True,
            is_visible=True,
            is_interactive=True,
        )
        registry = ActionBuilder(context).build_default_actions()
        result = registry.execute(
            Action(name="scroll_to_bottom", args={"index": "3"}),
            {3: node},
        )
        page.resolve_scroll_target.assert_called()
        page.scroll_to_percent.assert_called()
        # Coerced index should resolve to the mapped element, not None.
        call_args = page.resolve_scroll_target.call_args
        self.assertIs(call_args[0][0], node)
        self.assertIn("container", result.extracted_content or "")


if __name__ == "__main__":
    unittest.main()
