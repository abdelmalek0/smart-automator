import unittest

from smart_automator.browser.dom import DOMElementNode, DOMTextNode
from smart_automator.browser.observation import bounded_clickable_elements_to_string


def _button(index: int, label: str, *, is_new: bool = False) -> DOMElementNode:
    return DOMElementNode(
        tag_name="button",
        xpath=f"/button[{index}]",
        attributes={"aria-label": label},
        highlight_index=index,
        is_new=is_new,
        is_in_viewport=True,
        is_visible=True,
        is_interactive=True,
        is_top_element=True,
    )


def _input_field(index: int, placeholder: str) -> DOMElementNode:
    return DOMElementNode(
        tag_name="input",
        xpath=f"/input[{index}]",
        attributes={"placeholder": placeholder, "type": "text"},
        highlight_index=index,
        is_in_viewport=True,
        is_visible=True,
        is_interactive=True,
        is_top_element=True,
    )


def _text_block(text: str, *, parent: DOMElementNode) -> DOMTextNode:
    return DOMTextNode(text=text, is_visible=True, parent=parent)


def _heading(text: str) -> DOMElementNode:
    heading = DOMElementNode(
        tag_name="h1",
        xpath=f"/h1/{text}",
        is_visible=True,
        is_top_element=True,
        children=[],
    )
    heading.children = [_text_block(text, parent=heading)]
    return heading


class TestObservationBounds(unittest.TestCase):
    def test_caps_element_count(self):
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

    def test_prioritizes_inputs_and_submit_controls(self):
        children = [
            _button(0, "footer link"),
            _input_field(1, "Search query"),
            _button(2, "Submit search"),
        ]
        root = DOMElementNode(tag_name="body", xpath="/body", children=children)
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label", "placeholder", "type"],
            max_elements=2,
            max_chars=50000,
        )
        self.assertEqual(total, 3)
        self.assertEqual(shown, 2)
        self.assertIn("[1]", text)
        self.assertIn("[2]", text)
        self.assertNotIn("[0]", text)

    def test_includes_visible_text_section(self):
        heading = _heading("Thank you for your order")
        root = DOMElementNode(tag_name="body", xpath="/body", children=[heading])
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=80,
            max_chars=50000,
        )
        self.assertEqual(shown, 0)
        self.assertEqual(total, 0)
        self.assertIn("[Visible text]", text)
        self.assertIn("Thank you for your order", text)

    def test_does_not_duplicate_clickable_label_in_visible_text(self):
        close = _button(0, "Close")
        heading = _heading("Close")
        root = DOMElementNode(tag_name="body", xpath="/body", children=[heading, close])
        text, _, _ = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=80,
            max_chars=50000,
        )
        self.assertIn("[0]", text)
        visible_text_lines = [
            line
            for line in text.splitlines()
            if line and line != "[Visible text]" and not line.startswith("[")
        ]
        self.assertEqual(visible_text_lines, [])

    def test_interactives_win_when_budget_is_tight(self):
        long_label = "x" * 200
        children = [_button(i, f"{long_label}-{i}") for i in range(40)]
        heading = _heading("Order confirmation visible on page")
        root = DOMElementNode(tag_name="body", xpath="/body", children=[heading, *children])
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=80,
            max_chars=1200,
        )
        self.assertGreater(shown, 0)
        self.assertEqual(total, 40)
        self.assertNotIn("Order confirmation visible on page", text)


if __name__ == "__main__":
    unittest.main()
