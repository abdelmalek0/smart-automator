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

    def test_reserves_visible_text_when_budget_is_tight(self):
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
        self.assertIn("[Visible text]", text)
        self.assertIn("Order confirmation visible on page", text)

    def test_offscreen_marker_and_viewport_first_fill(self):
        viewport = [_button(i, f"vp-{i}") for i in range(3)]
        offscreen = [
            DOMElementNode(
                tag_name="button",
                xpath=f"/button[{i}]",
                attributes={"aria-label": f"off-{i}"},
                highlight_index=i,
                is_in_viewport=False,
                is_visible=True,
                is_interactive=True,
                is_top_element=False,
            )
            for i in range(3, 8)
        ]
        root = DOMElementNode(tag_name="body", xpath="/body", children=[*viewport, *offscreen])
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=4,
            max_chars=50000,
        )
        self.assertEqual(total, 8)
        self.assertEqual(shown, 4)
        self.assertIn("[0]", text)
        self.assertIn("[1]", text)
        self.assertIn("[2]", text)
        self.assertIn("(offscreen)", text)
        # One offscreen slot after three viewport items
        self.assertIn("[3]", text)
        self.assertNotIn("[4]", text)
        self.assertIn("offscreen interactives omitted", text)

    def test_flutter_static_rows_appear_without_top_element(self):
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
        label.children = [_text_block("Total Refund", parent=label)]
        amount.children = [_text_block("20.00", parent=amount)]
        chrome = _button(0, "Close Shift")
        root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[chrome, label, amount],
        )
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=80,
            max_chars=50000,
        )
        self.assertEqual(shown, 1)
        self.assertEqual(total, 1)
        self.assertIn("[Visible text]", text)
        self.assertIn("Total Refund", text)
        self.assertIn("20.00", text)

    def test_noninteractive_aria_label_appears_in_visible_text(self):
        row = DOMElementNode(
            tag_name="flt-semantics",
            xpath="/flt-semantics[1]",
            attributes={"aria-label": "Total Refund: 20.00"},
            is_visible=True,
            is_top_element=False,
        )
        root = DOMElementNode(tag_name="body", xpath="/body", children=[row])
        text, shown, total = bounded_clickable_elements_to_string(
            root,
            ["aria-label"],
            max_elements=80,
            max_chars=50000,
        )
        self.assertEqual(shown, 0)
        self.assertEqual(total, 0)
        self.assertIn("[Visible text]", text)
        self.assertIn("Total Refund: 20.00", text)

    def _static_copy(self, tag: str, text: str, *, role: str | None = None) -> DOMElementNode:
        node = DOMElementNode(
            tag_name=tag,
            xpath=f"/{tag}/{text}",
            attributes={"role": role} if role else {},
            is_visible=True,
            is_top_element=False,
            children=[],
        )
        node.children = [_text_block(text, parent=node)]
        return node

    def test_html_paragraphs_appear_without_top_element(self):
        root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[
                self._static_copy("p", "Total Refund"),
                self._static_copy("p", "20.00"),
            ],
        )
        text, shown, total = bounded_clickable_elements_to_string(
            root, ["aria-label"], max_elements=80, max_chars=50000
        )
        self.assertEqual(shown, 0)
        self.assertEqual(total, 0)
        self.assertIn("[Visible text]", text)
        self.assertIn("Total Refund", text)
        self.assertIn("20.00", text)

    def test_js_leaf_div_and_span_appear_without_top_element(self):
        root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[
                self._static_copy("div", "Total Refund"),
                self._static_copy("span", "20.00"),
            ],
        )
        text, _, _ = bounded_clickable_elements_to_string(
            root, ["aria-label"], max_elements=80, max_chars=50000
        )
        self.assertIn("[Visible text]", text)
        self.assertIn("Total Refund", text)
        self.assertIn("20.00", text)

    def test_js_role_text_appears_without_top_element(self):
        root = DOMElementNode(
            tag_name="body",
            xpath="/body",
            children=[self._static_copy("div", "Total Refund 20.00", role="text")],
        )
        text, _, _ = bounded_clickable_elements_to_string(
            root, ["aria-label"], max_elements=80, max_chars=50000
        )
        self.assertIn("Total Refund 20.00", text)

    def test_wrapper_div_is_not_treated_as_paragraph(self):
        inner = self._static_copy("p", "Total Refund")
        wrapper = DOMElementNode(
            tag_name="div",
            xpath="/div/wrap",
            is_visible=True,
            is_top_element=False,
            children=[inner],
        )
        inner.parent = wrapper
        root = DOMElementNode(tag_name="body", xpath="/body", children=[wrapper])
        text, _, _ = bounded_clickable_elements_to_string(
            root, ["aria-label"], max_elements=80, max_chars=50000
        )
        self.assertIn("Total Refund", text)
        visible_text_lines = [
            line
            for line in text.splitlines()
            if line and line != "[Visible text]" and not line.startswith("[")
        ]
        self.assertEqual(visible_text_lines, ["Total Refund"])

    def test_flutter_long_paragraph_appears_without_top_element(self):
        paragraph = "Refund confirmed. " + ("The cashier report lists the amount. " * 20)
        self.assertGreater(len(paragraph), 400)
        node = self._static_copy("flt-semantics", paragraph)
        root = DOMElementNode(tag_name="body", xpath="/body", children=[node])
        text, _, _ = bounded_clickable_elements_to_string(
            root, ["aria-label"], max_elements=80, max_chars=50000
        )
        self.assertIn("[Visible text]", text)
        self.assertIn("Refund confirmed.", text)


if __name__ == "__main__":
    unittest.main()
