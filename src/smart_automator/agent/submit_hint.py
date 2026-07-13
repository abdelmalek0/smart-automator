from __future__ import annotations

import re

from ..actions.schemas import Action
from ..browser.dom import DOMElementNode
from ..browser.views import BrowserState

_SUBMIT_PATTERN = re.compile(
    r"\b(enter|ok|submit|confirm|continue|proceed|next|done|go|sign\s*in|log\s*in)\b",
    re.I,
)


def _element_label(node: DOMElementNode) -> str:
    parts: list[str] = [node.get_all_text_till_next_clickable_element()]
    for attr in ("aria-label", "title", "placeholder", "value"):
        value = node.attributes.get(attr)
        if value:
            parts.append(str(value))
    return " ".join(parts).strip()


def find_submit_button_indices(selector_map: dict[int, DOMElementNode]) -> list[int]:
    matches: list[int] = []
    for index, node in selector_map.items():
        label = _element_label(node)
        if label and _SUBMIT_PATTERN.search(label):
            matches.append(index)
    return sorted(matches)


def build_submit_completeness_hint(
    actions: list[Action],
    before_state: BrowserState,
    after_state: BrowserState,
) -> str | None:
    if before_state.url != after_state.url or before_state.title != after_state.title:
        return None

    click_count = sum(1 for action in actions if action.name == "click_element")
    had_entry = any(action.name == "input_text" for action in actions) or click_count >= 2
    if not had_entry:
        return None

    submit_indices = find_submit_button_indices(after_state.selector_map)
    if not submit_indices:
        return None

    clicked = {
        action.index
        for action in actions
        if action.name == "click_element" and action.index is not None
    }
    if any(index in clicked for index in submit_indices):
        return None

    index_list = ", ".join(str(index) for index in submit_indices[:3])
    return (
        "Form or PIN entry may be incomplete: Enter/OK/Submit button(s) are still visible "
        f"at index(es) {index_list}. Click the confirm button to apply the entry before continuing."
    )
