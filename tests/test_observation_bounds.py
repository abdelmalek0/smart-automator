import unittest

from smart_automator.browser.dom import DOMElementNode
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


if __name__ == "__main__":
    unittest.main()
