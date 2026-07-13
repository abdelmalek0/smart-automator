from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..actions.schemas import Action
from .context import ActionResult
from .verification import (
    VERIFICATION_FAILED,
    VERIFICATION_VERIFIED,
    ElementLiveState,
    format_verification_summary,
    probe_element,
)

if TYPE_CHECKING:
    from ..browser.dom import DOMElementNode
    from ..browser.page import Page
    from ..browser.views import BrowserState
    from .context import AgentContext
    from .verification import PageSnapshot

MUTATION_ACTIONS = frozenset({"input_text", "select_dropdown_option"})
_COMMIT_LABEL_PATTERN = re.compile(
    r"\b(submit|sign\s*in|log\s*in|enter|ok|confirm|continue|next|apply|save|done)\b",
    re.IGNORECASE,
)


@dataclass
class MutationRecord:
    action: Action
    element: DOMElementNode
    expected_value: str | None = None
    expected_selected_text: str | None = None


@dataclass
class BatchState:
    mutations: list[MutationRecord] = field(default_factory=list)
    mutation_indices: set[int] = field(default_factory=set)


def action_to_dict(action: Action) -> dict[str, Any]:
    return {action.name: dict(action.args)}


def format_all_actions_args(actions: list[Action]) -> dict[str, Any]:
    if not actions:
        return {}
    if len(actions) == 1:
        action = actions[0]
        return {action.name: dict(action.args), "actions": [action_to_dict(action)]}
    return {"actions": [action_to_dict(action) for action in actions]}


def format_action_results_with_verification(action_results: list[ActionResult]) -> str:
    parts: list[str] = []
    for result in action_results:
        if result.error:
            parts.append(f"Error: {result.error}")
            continue
        base = result.extracted_content or "OK"
        if result.verification_status != "unverified":
            parts.append(f"{base} | {format_verification_summary(result)}")
        else:
            parts.append(base)
    return "\n".join(parts) if parts else "OK"


def is_mutation_action(action: Action) -> bool:
    return action.name in MUTATION_ACTIONS


def _element_label(element: DOMElementNode) -> str:
    for attr in ("aria-label", "placeholder", "title", "name", "type"):
        value = element.attributes.get(attr, "").strip()
        if value:
            return value
    text = element.get_all_text_till_next_clickable_element().strip()
    return text or element.tag_name


def is_commit_action(action: Action, element: DOMElementNode | None = None) -> bool:
    if action.name == "send_keys":
        keys = str(action.args.get("keys", "")).strip().lower()
        return keys in {"enter", "return"}
    if action.name != "click_element" or element is None:
        return False
    label = _element_label(element)
    if not label:
        return False
    tag = element.tag_name.lower()
    input_type = element.attributes.get("type", "").strip().lower()
    if tag == "button" or input_type in {"submit", "button"}:
        return True
    return bool(_COMMIT_LABEL_PATTERN.search(label))


def mutation_is_verified(record: MutationRecord, state: ElementLiveState) -> tuple[bool, str]:
    if not state.exists:
        return False, f"[{record.action.index}] target missing"
    if record.action.name == "input_text":
        expected = record.expected_value or ""
        if state.value_matches is True:
            return True, f"[{record.action.index}] value present (len={state.value_length})"
        if expected and state.value_length > 0:
            return False, (
                f"[{record.action.index}] value length {state.value_length}, "
                f"expected {len(expected)}"
            )
        return False, f"[{record.action.index}] empty after mutation"
    if record.action.name == "select_dropdown_option":
        if state.selected_matches is True or state.selected_text_length > 0:
            return True, f"[{record.action.index}] option selected"
        return False, f"[{record.action.index}] option not selected"
    return state.exists, f"[{record.action.index}] present"


def reverify_mutations(
    page: Page,
    batch: BatchState,
) -> tuple[bool, list[str]]:
    issues: list[str] = []
    for record in batch.mutations:
        state = probe_element(
            page,
            record.element,
            expected_value=record.expected_value,
            expected_selected_text=record.expected_selected_text,
        )
        ok, detail = mutation_is_verified(record, state)
        if not ok:
            issues.append(detail)
    return not issues, issues


def format_related_control_states(
    page: Page,
    selector_map: dict[int, DOMElementNode],
    *,
    focus_indices: set[int] | None = None,
    limit: int = 8,
) -> str:
    if not selector_map:
        return ""
    focus = focus_indices or set()
    lines: list[str] = []
    for index in sorted(selector_map):
        if focus and index not in focus:
            continue
        element = selector_map[index]
        state = probe_element(page, element)
        if not state.exists or not state.visible:
            continue
        label = _element_label(element)
        if element.tag_name.lower() in {"input", "textarea", "select"}:
            if state.value_length > 0:
                status = f"value len={state.value_length}"
            else:
                status = "empty"
        elif state.checked is not None:
            status = "checked" if state.checked else "unchecked"
        elif state.selected_text_length > 0:
            status = "selected"
        else:
            status = "ready"
        if state.disabled:
            status += ", disabled"
        lines.append(f"[{index}] {label}: {status}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "Related control state: " + ", ".join(lines)


def build_post_commit_no_wait_hint(
    context: AgentContext,
    browser_state: BrowserState,
    planned_actions: list[Action],
) -> str | None:
    if not context.last_step_had_commit:
        return None
    if context.last_commit_snapshot is None:
        return None
    same_page = (
        context.last_commit_snapshot.url == browser_state.url
        and context.last_commit_snapshot.title == browser_state.title
    )
    if not same_page:
        return None
    only_wait = bool(planned_actions) and all(action.name == "wait" for action in planned_actions)
    if not only_wait:
        return None
    return (
        "Previous step submitted on this page but the screen did not advance. "
        "Re-check verified field values and retry the commit — do not wait."
    )


def record_commit_outcome(
    context: AgentContext,
    *,
    snapshot: PageSnapshot,
    had_commit: bool,
    page_advanced: bool,
) -> None:
    context.last_step_had_commit = had_commit and not page_advanced
    context.last_commit_snapshot = snapshot if context.last_step_had_commit else None
