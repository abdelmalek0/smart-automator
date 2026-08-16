"""Tests for criteria-specific verification observation."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.context import AgentContext, AgentOptions
from smart_automator.agents.criteria_checker import (
    CRITERIA_MAX_OBSERVATION_CHARS,
    CRITERIA_MAX_OBSERVATION_ELEMENTS,
    CriteriaCheckerAgent,
)
from smart_automator.browser.accessible_names import format_accessible_names_section
from smart_automator.browser.dom import DOMElementNode, DOMTextNode
from smart_automator.browser.observation import bounded_clickable_elements_to_string
from smart_automator.browser.views import BrowserState
from smart_automator.utils.prompts import build_browser_state_message


def _button(index: int, label: str) -> DOMElementNode:
    return DOMElementNode(
        tag_name="button",
        xpath=f"/button[{index}]",
        attributes={"aria-label": label},
        highlight_index=index,
        is_in_viewport=True,
        is_visible=True,
        is_interactive=True,
        is_top_element=True,
    )


def _heading(text: str) -> DOMElementNode:
    heading = DOMElementNode(
        tag_name="h1",
        xpath=f"/h1/{text}",
        is_visible=True,
        is_top_element=True,
        children=[],
    )
    heading.children = [DOMTextNode(text=text, is_visible=True, parent=heading)]
    return heading


class TestAccessibleNamesSection(unittest.TestCase):
    def test_format_accessible_names_section(self):
        section = format_accessible_names_section(["Cart (2)", "PAY 49.00"])
        self.assertIn("[Accessible names]", section)
        self.assertIn("Cart (2)", section)
        self.assertIn("PAY 49.00", section)
        self.assertIn("not clickable", section)

    def test_format_empty_names(self):
        self.assertEqual(format_accessible_names_section([]), "")


class TestCriteriaObservationBudgets(unittest.TestCase):
    def test_verification_budgets_exceed_navigator_defaults(self):
        self.assertGreater(CRITERIA_MAX_OBSERVATION_ELEMENTS, 120)
        self.assertGreater(CRITERIA_MAX_OBSERVATION_CHARS, 16000)

    def test_build_browser_state_message_honors_max_overrides(self):
        children = [_button(i, f"item-{i}") for i in range(120)]
        root = DOMElementNode(tag_name="body", xpath="/body", children=children)
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            element_tree=root,
            selector_map={i: children[i] for i in range(120)},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )
        context = AgentContext(
            task_id="t1",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(max_observation_elements=80, max_observation_chars=12000),
        )
        message = build_browser_state_message(
            context,
            browser_state,
            include_action_results=False,
            max_elements=200,
            max_chars=50000,
        )
        # Navigator default would truncate to 80; override keeps all 120.
        self.assertNotIn("truncated", message)
        self.assertIn("[0]", message)
        self.assertIn("[119]", message)
        text, shown, total = bounded_clickable_elements_to_string(
            root, ["aria-label"], max_elements=200, max_chars=50000
        )
        self.assertEqual(shown, 120)
        self.assertEqual(total, 120)

    def test_navigator_bounds_unchanged_without_override(self):
        children = [_button(i, f"btn-{i}") for i in range(120)]
        root = DOMElementNode(tag_name="body", xpath="/body", children=children)
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=80,
            max_chars=50000,
        )
        self.assertEqual(total, 120)
        self.assertLessEqual(shown, 80)
        self.assertIn("truncated 40 of 120", text)


class TestCriteriaBuildStateMessage(unittest.TestCase):
    def test_includes_accessible_names_and_uses_verification_budgets(self):
        heading = _heading("Order confirmed")
        pay = _button(0, "PAY 49.00")
        root = DOMElementNode(tag_name="body", xpath="/body", children=[heading, pay])
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com/done",
            title="Done",
            element_tree=root,
            selector_map={0: pay},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )
        browser_context = MagicMock()
        browser_context.get_state.return_value = browser_state
        page = MagicMock()
        browser_context.get_current_page.return_value = page

        context = AgentContext(
            task_id="t1",
            browser_context=browser_context,
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        context.success_criteria = "Confirmation is visible"

        with patch(
            "smart_automator.browser.accessible_names.collect_accessible_names",
            return_value=["Cart (2)", "Meal Fajita", "PAY 49.00"],
        ) as mock_collect:
            message = CriteriaCheckerAgent.build_state_message(context)

        browser_context.get_state.assert_called_once_with(
            show_highlights=False,
            wait_for_stable=True,
        )
        mock_collect.assert_called_once()
        kwargs = mock_collect.call_args.kwargs
        self.assertEqual(kwargs["max_names"], 200)
        self.assertEqual(kwargs["max_chars"], 12000)
        self.assertIn("https://example.com/done", message)
        self.assertIn("[Accessible names]", message)
        self.assertIn("Cart (2)", message)
        self.assertIn("Meal Fajita", message)
        self.assertIn("PAY 49.00", message)

    def test_navigator_state_includes_shift_refund_text(self):
        close = _button(0, "Close Shift")
        label = DOMElementNode(
            tag_name="flt-semantics",
            xpath="/flt-semantics[1]",
            is_visible=True,
            is_top_element=False,
            children=[],
        )
        amount = DOMElementNode(
            tag_name="flt-semantics",
            xpath="/flt-semantics[2]",
            is_visible=True,
            is_top_element=False,
            children=[],
        )
        label.children = [DOMTextNode(text="Total Refund", is_visible=True, parent=label)]
        amount.children = [DOMTextNode(text="20.00", is_visible=True, parent=amount)]
        root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[close, label, amount],
        )
        browser_state = BrowserState(
            tab_id=0,
            url="https://pos.example/shift",
            title="Shift Summary",
            element_tree=root,
            selector_map={0: close},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )
        context = AgentContext(
            task_id="t1",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        with patch(
            "smart_automator.utils.prompts.collect_accessible_names_section",
            return_value="[Accessible names]\nTotal Refund 20.00\nNote: accessible names are read-only page labels for verification — not clickable.\n",
        ):
            message = build_browser_state_message(
                context,
                browser_state,
                include_action_results=False,
            )
        self.assertIn("[Visible text]", message)
        self.assertIn("Total Refund", message)
        self.assertIn("20.00", message)
        self.assertIn("[Accessible names]", message)

    def _not_top_copy(self, tag: str, text: str) -> DOMElementNode:
        node = DOMElementNode(
            tag_name=tag,
            xpath=f"/{tag}/{text}",
            is_visible=True,
            is_top_element=False,
            children=[],
        )
        node.children = [DOMTextNode(text=text, is_visible=True, parent=node)]
        return node

    def test_navigator_state_includes_html_and_js_refund_text(self):
        html_root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[self._not_top_copy("p", "Total Refund"), self._not_top_copy("p", "20.00")],
        )
        js_root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[self._not_top_copy("div", "Total Refund"), self._not_top_copy("span", "20.00")],
        )
        context = AgentContext(
            task_id="t1",
            browser_context=MagicMock(),
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        with patch(
            "smart_automator.utils.prompts.collect_accessible_names_section",
            return_value="",
        ):
            for root in (html_root, js_root):
                browser_state = BrowserState(
                    tab_id=0,
                    url="https://example.com/shift",
                    title="Shift",
                    element_tree=root,
                    selector_map={},
                    tabs=[],
                    scroll_y=0,
                    scroll_height=1000,
                    visual_viewport_height=800,
                )
                message = build_browser_state_message(
                    context,
                    browser_state,
                    include_action_results=False,
                )
                self.assertIn("[Visible text]", message)
                self.assertIn("Total Refund", message)
                self.assertIn("20.00", message)

    def test_accessible_names_failure_still_returns_page_state(self):
        browser_state = BrowserState(
            tab_id=0,
            url="https://example.com",
            title="Example",
            element_tree=DOMElementNode(tag_name="body", xpath="/body"),
            selector_map={},
            tabs=[],
            scroll_y=0,
            scroll_height=1000,
            visual_viewport_height=800,
        )
        browser_context = MagicMock()
        browser_context.get_state.return_value = browser_state
        browser_context.get_current_page.side_effect = RuntimeError("no page")

        context = AgentContext(
            task_id="t1",
            browser_context=browser_context,
            message_manager=MagicMock(),
            options=AgentOptions(),
        )
        message = CriteriaCheckerAgent.build_state_message(context)
        self.assertIn("https://example.com", message)
        self.assertNotIn("[Accessible names]", message)


class TestBuildDomTreeAccessibleBypass(unittest.TestCase):
    def test_script_defines_accessible_identity_helper(self):
        from pathlib import Path

        script = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "smart_automator"
            / "browser"
            / "assets"
            / "buildDomTree.js"
        ).read_text()
        self.assertIn("function hasMeaningfulAccessibleIdentity", script)
        self.assertIn("hasMeaningfulAccessibleIdentity(node)", script)
        self.assertIn("hasAttribute('aria-label')", script)
        self.assertNotIn("hasAttribute('aria-')", script)
        self.assertIn("element.textContent", script)
        self.assertIn("textBearingTags", script)
        self.assertIn("isLeafDiv", script)
        # Hit-testing skipped for accessible nodes; viewport check retained.
        self.assertIn("isInExpandedViewport(node, viewportExpansion)", script)
        self.assertIn("indexOffscreenElements", script)
        self.assertIn("isOffscreenIndexEligible", script)
        self.assertIn("findActiveBlockingDialog", script)


class TestAccessibleNamesHarvestScript(unittest.TestCase):
    def test_harvests_flutter_semantics_without_role(self):
        from smart_automator.browser import accessible_names as an

        script = an._COLLECT_ACCESSIBLE_NAMES_JS
        self.assertIn("isFlutterSemantics", script)
        self.assertIn("maxInnerText", script)
        self.assertIn("text.slice(0, maxInnerText)", script)
        self.assertNotIn("text.length <= 120", script)
        self.assertEqual(an._MAX_INNER_TEXT_CHARS, 400)
        self.assertIn("!isFlutterSemantics && style.opacity === '0'", script)


class TestPlannerSettle(unittest.TestCase):
    def test_planner_snapshot_waits_for_stable(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "smart_automator"
            / "agent"
            / "executor.py"
        ).read_text()
        self.assertIn("wait_for_stable=True", src)
        planner_block = src[src.index("def _run_planner") : src.index("def _inject_stuck_recovery_hint")]
        self.assertIn("wait_for_stable=True", planner_block)
        self.assertNotIn("wait_for_stable=False", planner_block)


if __name__ == "__main__":
    unittest.main()
