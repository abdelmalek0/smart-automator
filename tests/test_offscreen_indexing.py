"""Tests for off-screen indexing config plumbing and HITL scroll capture."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from smart_automator.agent.context import AgentContext, AgentOptions
from smart_automator.agent.hitl import HumanActionRecorder
from smart_automator.browser.dom import _run_build_dom_tree_raw
from smart_automator.config import Config, load_config
from smart_automator.utils.prompts import build_browser_state_message, get_navigator_system_prompt
from smart_automator.browser.dom import DOMElementNode
from smart_automator.browser.views import BrowserState


class TestIndexOffscreenConfig(unittest.TestCase):
    def test_config_defaults(self):
        cfg = Config()
        self.assertTrue(cfg.index_offscreen_elements)
        self.assertEqual(cfg.max_observation_elements, 120)
        self.assertEqual(cfg.max_observation_chars, 16000)

    def test_env_can_disable_offscreen_indexing(self):
        import os

        previous = os.environ.get("INDEX_OFFSCREEN_ELEMENTS")
        os.environ["INDEX_OFFSCREEN_ELEMENTS"] = "false"
        try:
            cfg = load_config()
            self.assertFalse(cfg.index_offscreen_elements)
        finally:
            if previous is None:
                os.environ.pop("INDEX_OFFSCREEN_ELEMENTS", None)
            else:
                os.environ["INDEX_OFFSCREEN_ELEMENTS"] = previous


class TestBuildDomTreeArgsContract(unittest.TestCase):
    def test_script_exposes_offscreen_helpers(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "smart_automator"
            / "browser"
            / "assets"
            / "buildDomTree.js"
        ).read_text()
        self.assertIn("indexOffscreenElements", script)
        self.assertIn("function isOffscreenIndexEligible", script)
        self.assertIn("function findActiveBlockingDialog", script)
        self.assertIn('aria-modal="true"', script)

    def test_run_raw_passes_index_offscreen_flag(self):
        calls: list[dict] = []

        class FakeFrame:
            def evaluate(self, _script, args=None):
                if args is not None:
                    calls.append(args)
                return {"map": {}, "rootId": "0"}

        from unittest.mock import patch

        with patch(
            "smart_automator.browser.dom.ensure_build_dom_tree_script_on_frame"
        ):
            _run_build_dom_tree_raw(
                FakeFrame(),
                show_highlights=False,
                do_highlight_elements=False,
                focus_element=-1,
                viewport_expansion=0,
                start_highlight_index=0,
                start_id=0,
                debug_mode=False,
                index_offscreen_elements=False,
            )
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["indexOffscreenElements"])
        self.assertEqual(calls[0]["viewportExpansion"], 0)


class TestHitlScrollCapture(unittest.TestCase):
    def test_record_window_scroll(self):
        context = AgentContext(
            task_id="t",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        recorder = HumanActionRecorder(context)
        recorder._active = True
        recorder._handle_capture_event(
            {
                "eventType": "scroll",
                "scrollKind": "window",
                "percent": 42,
                "tagName": "html",
                "xpath": "",
                "attributes": {},
            }
        )
        self.assertEqual(len(recorder.recorded), 1)
        name, args, result = recorder.recorded[0]
        self.assertEqual(name, "scroll_to_percent")
        self.assertEqual(args["percent"], 42)
        self.assertEqual(args["yPercent"], 42)
        self.assertNotIn("xpath", args)
        self.assertIn("Human scrolled to 42%", result.extracted_content or "")

    def test_coalesce_consecutive_scrolls(self):
        context = AgentContext(
            task_id="t",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        recorder = HumanActionRecorder(context)
        recorder._active = True
        for percent in (10, 25, 60):
            recorder._handle_capture_event(
                {
                    "eventType": "scroll",
                    "scrollKind": "window",
                    "percent": percent,
                    "tagName": "html",
                    "xpath": "",
                    "attributes": {},
                }
            )
        self.assertEqual(len(recorder.recorded), 1)
        self.assertEqual(recorder.recorded[0][1]["percent"], 60)

    def test_record_element_scroll_with_xpath(self):
        context = AgentContext(
            task_id="t",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        recorder = HumanActionRecorder(context)
        recorder._active = True
        recorder._handle_capture_event(
            {
                "eventType": "scroll",
                "scrollKind": "element",
                "percent": 80,
                "tagName": "div",
                "xpath": "html/body/div[2]",
                "attributes": {"role": "list"},
            }
        )
        name, args, _ = recorder.recorded[0]
        self.assertEqual(name, "scroll_to_percent")
        self.assertEqual(args["percent"], 80)
        self.assertEqual(args["xpath"], "html/body/div[2]")


class TestPromptOffscreenWording(unittest.TestCase):
    def test_navigator_prompt_mentions_offscreen(self):
        prompt = get_navigator_system_prompt()
        self.assertIn("(offscreen)", prompt)
        self.assertIn("scrolls them into view", prompt)

    def test_state_message_mentions_offscreen_note(self):
        button = DOMElementNode(
            tag_name="button",
            xpath="/button[1]",
            attributes={"aria-label": "Pay"},
            highlight_index=0,
            is_in_viewport=False,
            is_visible=True,
            is_interactive=True,
        )
        root = DOMElementNode(tag_name="body", xpath="/body", children=[button])
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            element_tree=root,
            selector_map={0: button},
            tabs=[],
            scroll_y=0,
            scroll_height=2000,
            visual_viewport_height=800,
        )
        context = AgentContext(
            task_id="t1",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        message = build_browser_state_message(context, browser_state)
        self.assertIn("current page", message)
        self.assertNotIn("inside the viewport", message)
        self.assertIn("(offscreen)", message)


if __name__ == "__main__":
    unittest.main()
