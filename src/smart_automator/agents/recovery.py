from __future__ import annotations

import json

from ..actions.schemas import ACTION_NAMES, Action
from ..agent.messages.utils import preview_text


def format_valid_indices(selector_map: dict, limit: int = 30) -> str:
    if not selector_map:
        return "none (page may still be loading)"
    indices = sorted(selector_map.keys())[:limit]
    suffix = "..." if len(selector_map) > limit else ""
    return f"{indices}{suffix}"


def build_parse_repair_message(
    *,
    error: str,
    valid_indices: str,
    rejected_actions: list | None = None,
) -> str:
    lines = [
        "Your last output was invalid or unusable.",
        f"Parse issue: {preview_text(error, 160)}",
        'Return ONLY flat JSON: {"current_state": {...}, "action": [{...}]}',
        f"Valid element indexes on this page: {valid_indices}",
        f"Allowed action names: {', '.join(ACTION_NAMES)}",
    ]
    if rejected_actions:
        lines.append(
            f"Rejected actions from your last response: {json.dumps(rejected_actions, ensure_ascii=False)}"
        )
    return "\n".join(lines)


def build_empty_action_repair_message(valid_indices: str) -> str:
    return (
        "Your response had no parseable actions but interactive elements exist. "
        'Return flat JSON with a non-empty action array using click_element, input_text, or wait. '
        f"Valid indexes: {valid_indices}"
    )


def build_invalid_index_message(invalid: list[dict], valid_indices: str) -> str:
    return (
        "Some actions used invalid element indexes and were skipped. "
        f"Invalid: {json.dumps(invalid, ensure_ascii=False)}. "
        f"Valid indexes on this page: {valid_indices}. "
        "Re-issue actions using only valid indexes."
    )


def filter_actions_by_selector_map(
    actions: list[Action],
    selector_map: dict,
) -> tuple[list[Action], list[dict]]:
    valid: list[Action] = []
    invalid: list[dict] = []
    for action in actions:
        if action.has_index() and action.index not in selector_map:
            invalid.append({action.name: action.args})
            continue
        valid.append(action)
    return valid, invalid


def collect_rejected_actions(raw_actions: list, validated_actions: list) -> list:
    if not raw_actions:
        return []
    validated_set = {json.dumps(item, sort_keys=True) for item in validated_actions}
    rejected: list = []
    for item in raw_actions:
        if not isinstance(item, dict):
            rejected.append(item)
            continue
        normalized = item
        if "type" in item and item["type"] in ACTION_NAMES:
            normalized = {item["type"]: {k: v for k, v in item.items() if k != "type"}}
        if json.dumps(normalized, sort_keys=True) not in validated_set:
            rejected.append(item)
    return rejected
