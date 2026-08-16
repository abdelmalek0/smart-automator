from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..actions.schemas import Action
from .context import ActionResult

if TYPE_CHECKING:
    from ..browser.dom import DOMElementNode
    from ..browser.page import Page

VERIFICATION_VERIFIED = "verified"
VERIFICATION_UNVERIFIED = "unverified"
VERIFICATION_NO_EFFECT = "no_effect"
VERIFICATION_FAILED = "failed"

_SENSITIVE_INPUT_TYPES = frozenset({"password"})


@dataclass
class PageSnapshot:
    url: str
    title: str
    scroll_y: int
    tab_ids: tuple[int, ...] = ()
    dom_signature: int = 0
    interactive_count: int = 0
    scroll_fingerprint: tuple[tuple[str, int], ...] = ()

    def page_changed(self, other: PageSnapshot) -> bool:
        return self.url != other.url or self.title != other.title

    def dom_changed(self, other: PageSnapshot) -> bool:
        return self.dom_signature != other.dom_signature

    def tabs_changed(self, other: PageSnapshot) -> bool:
        return self.tab_ids != other.tab_ids

    def scroll_changed(self, other: PageSnapshot, *, tolerance: int = 2) -> bool:
        if abs(self.scroll_y - other.scroll_y) > tolerance:
            return True
        before = dict(self.scroll_fingerprint)
        after = dict(other.scroll_fingerprint)
        keys = set(before) | set(after)
        if not keys:
            return False
        for key in keys:
            if abs(int(before.get(key, 0)) - int(after.get(key, 0))) > tolerance:
                return True
        return False


@dataclass
class ElementLiveState:
    exists: bool = False
    tag_name: str = ""
    value_length: int = 0
    value_matches: bool | None = None
    disabled: bool = False
    visible: bool = False
    focused: bool = False
    checked: bool | None = None
    aria_checked: str | None = None
    aria_expanded: str | None = None
    selected_index: int | None = None
    selected_text_length: int = 0
    selected_matches: bool | None = None

    @classmethod
    def from_probe(cls, data: dict[str, Any] | None) -> ElementLiveState:
        if not data or not data.get("exists"):
            return cls(exists=False)
        return cls(
            exists=True,
            tag_name=str(data.get("tagName", "")),
            value_length=int(data.get("valueLength", 0)),
            value_matches=data.get("valueMatches"),
            disabled=bool(data.get("disabled")),
            visible=bool(data.get("visible")),
            focused=bool(data.get("focused")),
            checked=data.get("checked"),
            aria_checked=data.get("ariaChecked"),
            aria_expanded=data.get("ariaExpanded"),
            selected_index=data.get("selectedIndex"),
            selected_text_length=int(data.get("selectedTextLength", 0)),
            selected_matches=data.get("selectedMatches"),
        )


def is_sensitive_input(element: DOMElementNode | None) -> bool:
    if element is None:
        return False
    input_type = element.attributes.get("type", "").strip().lower()
    return input_type in _SENSITIVE_INPUT_TYPES


def redact_input_message(index: int | None, text: str, element: DOMElementNode | None) -> str:
    if is_sensitive_input(element):
        return f"Typed into element {index} (len={len(text)})"
    preview = text if len(text) <= 32 else f"{text[:32]}…"
    return f"Typed '{preview}' into element {index}"


def format_verification_summary(result: ActionResult) -> str:
    index_part = f" [{result.action_index}]" if result.action_index is not None else ""
    name = result.action_name or "action"
    status = result.verification_status
    evidence = result.verification_evidence or ""
    if evidence:
        return f"{name}{index_part}: {status} ({evidence})"
    return f"{name}{index_part}: {status}"


def format_verification_hints(action_results: list[ActionResult]) -> str | None:
    issues = [
        result
        for result in action_results
        if result.verification_status in {VERIFICATION_NO_EFFECT, VERIFICATION_FAILED}
        or result.error
    ]
    if not issues:
        return None
    lines = ["Action verification on last step:"]
    for result in issues:
        lines.append(f"- {format_verification_summary(result)}")
        if result.error:
            lines.append(f"  error: {result.error.split(chr(10))[-1]}")
    return "\n".join(lines)


def count_verification_issues(action_results: list[ActionResult]) -> dict[str, int]:
    counts = {
        VERIFICATION_VERIFIED: 0,
        VERIFICATION_UNVERIFIED: 0,
        VERIFICATION_NO_EFFECT: 0,
        VERIFICATION_FAILED: 0,
    }
    for result in action_results:
        key = result.verification_status
        if key in counts:
            counts[key] += 1
    return counts


def apply_verification(
    action: Action,
    result: ActionResult,
    *,
    before: PageSnapshot,
    after: PageSnapshot,
    before_element: ElementLiveState | None,
    after_element: ElementLiveState | None,
    element: DOMElementNode | None = None,
) -> ActionResult:
    result.action_name = action.name
    result.action_index = action.index

    if result.error:
        result.verification_status = VERIFICATION_FAILED
        result.verification_evidence = result.error.split("\n")[-1][:160]
        return result

    if action.name in {"done", "cache_content", "wait", "get_dropdown_options"}:
        result.verification_status = VERIFICATION_VERIFIED
        result.verification_evidence = "informational action"
        return result

    if action.name == "input_text":
        expected = str(action.args.get("text", ""))
        if after_element and after_element.exists:
            if after_element.value_matches is True:
                result.verification_status = VERIFICATION_VERIFIED
                result.verification_evidence = f"value set (len={after_element.value_length})"
            elif after_element.value_length > 0 and expected:
                result.verification_status = VERIFICATION_FAILED
                result.verification_evidence = (
                    f"value length {after_element.value_length}, expected {len(expected)}"
                )
            else:
                result.verification_status = VERIFICATION_NO_EFFECT
                result.verification_evidence = "input still empty after typing"
        else:
            result.verification_status = VERIFICATION_UNVERIFIED
            result.verification_evidence = "target not found for verification"
        return result

    if action.name == "select_dropdown_option":
        expected = str(action.args.get("text", "")).strip()
        if after_element and after_element.exists:
            if after_element.selected_matches is True or after_element.selected_text_length > 0:
                result.verification_status = VERIFICATION_VERIFIED
                result.verification_evidence = "option selected"
            else:
                result.verification_status = VERIFICATION_FAILED
                result.verification_evidence = f"option not selected"
        else:
            result.verification_status = VERIFICATION_UNVERIFIED
            result.verification_evidence = "select element unavailable"
        return result

    if action.name in {"click_element", "send_keys"}:
        effects: list[str] = []
        if before.page_changed(after):
            effects.append("navigation")
        if before.tabs_changed(after):
            effects.append("tab change")
        if before.dom_changed(after):
            effects.append("DOM update")
        if before.scroll_changed(after):
            effects.append("scroll change")
        if after_element and before_element:
            if after_element.checked != before_element.checked:
                effects.append("checked state changed")
            if after_element.aria_expanded != before_element.aria_expanded:
                effects.append("expanded state changed")
            if after_element.focused and not before_element.focused:
                effects.append("focus changed")
        if effects:
            result.verification_status = VERIFICATION_VERIFIED
            result.verification_evidence = ", ".join(effects)
        else:
            result.verification_status = VERIFICATION_NO_EFFECT
            result.verification_evidence = "no observable page effect"
        return result

    if action.name in {"go_to_url", "go_back", "search_google", "open_tab"}:
        if before.page_changed(after) or before.tabs_changed(after):
            result.verification_status = VERIFICATION_VERIFIED
            result.verification_evidence = "navigation confirmed"
        else:
            result.verification_status = VERIFICATION_NO_EFFECT
            result.verification_evidence = "navigation not observed"
        return result

    if action.name in {"switch_tab", "close_tab"}:
        if before.tabs_changed(after):
            result.verification_status = VERIFICATION_VERIFIED
            result.verification_evidence = "tab state changed"
        else:
            result.verification_status = VERIFICATION_NO_EFFECT
            result.verification_evidence = "tab state unchanged"
        return result

    if action.name in {
        "scroll_to_percent",
        "scroll_to_top",
        "scroll_to_bottom",
        "previous_page",
        "next_page",
        "scroll_to_text",
    }:
        content = (result.extracted_content or "").lower()
        if action.name == "scroll_to_text" and "not found" in content:
            result.verification_status = VERIFICATION_FAILED
            result.verification_evidence = "target text not found"
            return result
        if (
            before.scroll_changed(after)
            or "already" in content
            or "no scrollable region" in content
        ):
            result.verification_status = VERIFICATION_VERIFIED
            result.verification_evidence = "scroll position updated or at boundary"
        else:
            result.verification_status = VERIFICATION_NO_EFFECT
            result.verification_evidence = "scroll position unchanged"
        return result

    result.verification_status = VERIFICATION_UNVERIFIED
    result.verification_evidence = "no verifier for action type"
    return result


def capture_page_snapshot(page: Page, tab_ids: set[int]) -> PageSnapshot:
    return page.capture_snapshot(tab_ids)


def probe_element(
    page: Page,
    element: DOMElementNode | None,
    *,
    expected_value: str | None = None,
    expected_selected_text: str | None = None,
) -> ElementLiveState:
    if element is None:
        return ElementLiveState(exists=False)
    return ElementLiveState.from_probe(
        page.probe_element_state(
            element,
            expected_value=expected_value,
            expected_selected_text=expected_selected_text,
        )
    )
