"""Tests for referential screen excerpts (verbatim page copy, not parsed fields)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from smart_automator.agent.context import AgentContext, AgentOptions, AgentStepInfo
from smart_automator.agent.findings import (
    ScreenExcerpt,
    capture_screen_excerpt,
    clip_page_copy,
    format_excerpts_for_checker,
    is_referential_criteria,
    missing_historical_excerpts_note,
)


def _context(*, referential: bool = True) -> AgentContext:
    context = AgentContext(
        task_id="t1",
        browser_context=MagicMock(),
        message_manager=MagicMock(),
        options=AgentOptions(),
    )
    context.referential_criteria = referential
    context.criteria_keywords = {"refund", "amount", "total"}
    return context


SPLIT_REFUND = """[Task history memory ends]
[Current state starts here]
Current tab: {id: 0, url: https://pos.example/, title: SmartPOS}
[Start of page]
[0]<button>Close Shift</button>
[Visible text]
Total Refund
20.00
[End of page]

[Accessible names]
Total Refund 20.00
"""

CART = """[Visible text]
Hot Chocolate
20.00
Cash
[Accessible names]
PAY 20.00
"""

CHROME = """[Visible text]
Shifts
Amount
Menu
[Accessible names]
Shifts
"""


class TestReferentialGate(unittest.TestCase):
    def test_present_only_is_not_referential(self):
        self.assertFalse(is_referential_criteria("Order confirmation is visible"))
        self.assertFalse(is_referential_criteria("Cart shows one item"))
        self.assertFalse(is_referential_criteria("Dashboard is visible"))

    def test_referential_criteria(self):
        self.assertTrue(
            is_referential_criteria(
                "Checkout total matches the amount we paid"
            )
        )
        self.assertTrue(
            is_referential_criteria(
                "The confirmation shows the same username we entered"
            )
        )


class TestClipPageCopy(unittest.TestCase):
    def test_keeps_split_label_and_amount_verbatim(self):
        clipped = clip_page_copy(SPLIT_REFUND)
        self.assertIn("Total Refund", clipped)
        self.assertIn("20.00", clipped)
        self.assertNotIn("[0]<button>", clipped)

    def test_keeps_non_price_copy(self):
        clipped = clip_page_copy(
            "[Visible text]\nUsername\nalice\n[Accessible names]\nProfile\n"
        )
        self.assertIn("Username", clipped)
        self.assertIn("alice", clipped)


class TestCaptureScreenExcerpt(unittest.TestCase):
    def test_present_only_stores_nothing(self):
        context = _context(referential=False)
        added = capture_screen_excerpt(
            context,
            SPLIT_REFUND,
            url="https://pos.example/",
            title="SmartPOS",
        )
        self.assertIsNone(added)
        self.assertEqual(context.screen_excerpts, [])

    def test_records_verbatim_split_flutter_copy(self):
        context = _context()
        context.step_info = AgentStepInfo(step_number=7, max_steps=30)
        added = capture_screen_excerpt(
            context,
            SPLIT_REFUND,
            url="https://pos.example/",
            title="SmartPOS",
        )
        self.assertIsNotNone(added)
        self.assertEqual(added.step, 8)
        self.assertIn("Total Refund", added.text)
        self.assertIn("20.00", added.text)
        self.assertEqual(len(context.screen_excerpts), 1)

    def test_unchanged_chrome_does_not_duplicate(self):
        context = _context()
        first = capture_screen_excerpt(context, CHROME, url="https://pos.example/", title="POS")
        second = capture_screen_excerpt(context, CHROME, url="https://pos.example/", title="POS")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(context.screen_excerpts), 1)

    def test_keeps_every_distinct_screen(self):
        context = _context()
        capture_screen_excerpt(context, CART, url="https://pos.example/cart", title="Cart")
        for index in range(10):
            capture_screen_excerpt(
                context,
                f"[Visible text]\nShifts\nMenu {index}\n",
                url="https://pos.example/",
                title="Menu",
            )
        self.assertEqual(len(context.screen_excerpts), 11)
        blob = "\n".join(excerpt.text for excerpt in context.screen_excerpts)
        self.assertIn("20.00", blob)
        self.assertIn("Hot Chocolate", blob)
        self.assertIn("Menu 0", blob)
        self.assertIn("Menu 9", blob)

    def test_summarizes_huge_paragraphs_but_keeps_short_copy(self):
        wall = (
            "This privacy policy describes in great detail how we collect, use, share, "
            "and retain your personal information across products and services including "
            "analytics partners and advertising networks. The refund amount on this page "
            "is 20.00 and must match the earlier cart. Additional boilerplate continues "
            "for many more words about cookies, tracking pixels, and lawful bases for "
            "processing under applicable regulations worldwide without adding new facts."
        )
        self.assertGreater(len(wall), 220)
        clipped = clip_page_copy(
            f"[Visible text]\nTotal Refund\n20.00\n{wall}\nHot Chocolate\n",
            keywords={"refund", "amount"},
        )
        self.assertIn("Total Refund", clipped)
        self.assertIn("20.00", clipped)
        self.assertIn("Hot Chocolate", clipped)
        self.assertIn("[summarized]", clipped)
        self.assertNotIn("tracking pixels", clipped)
        self.assertNotIn("lawful bases", clipped)

    def test_summarizes_wrapped_prose_blocks(self):
        wrapped = "\n".join([
            "This privacy policy describes in great detail how we collect, use, share,",
            "and retain your personal information across products and services including",
            "analytics partners and advertising networks worldwide. The refund amount is",
            "20.00 and must match the earlier cart without relying on navigator memory.",
            "Additional boilerplate continues for many more words about cookies and",
            "tracking pixels plus lawful bases for processing under applicable rules.",
        ])
        clipped = clip_page_copy(
            f"[Visible text]\nTotal Refund\n20.00\n\n{wrapped}\n",
            keywords={"refund"},
        )
        self.assertIn("Total Refund", clipped)
        self.assertIn("20.00", clipped)
        self.assertIn("[summarized]", clipped)
        self.assertNotIn("tracking pixels", clipped)


class TestExcerptFormatting(unittest.TestCase):
    def test_checker_block_includes_verbatim_text(self):
        block = format_excerpts_for_checker(
            [
                ScreenExcerpt(
                    step=8,
                    url="https://pos.example/",
                    title="SmartPOS",
                    text="Total Refund\n20.00",
                )
            ]
        )
        self.assertIn("THEN evidence", block)
        self.assertIn("step 8", block)
        self.assertIn("20.00", block)
        self.assertIn("Total Refund", block)

    def test_missing_note_only_when_referential_and_empty(self):
        self.assertTrue(
            missing_historical_excerpts_note(referential=True, excerpts=[])
        )
        self.assertEqual(
            missing_historical_excerpts_note(
                referential=True,
                excerpts=[
                    ScreenExcerpt(step=1, url="/", title="x", text="20.00"),
                ],
            ),
            "",
        )
        self.assertEqual(
            missing_historical_excerpts_note(referential=False, excerpts=[]),
            "",
        )


if __name__ == "__main__":
    unittest.main()
