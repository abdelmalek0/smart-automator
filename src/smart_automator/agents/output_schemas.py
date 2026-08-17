from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..actions.schemas import ACTION_NAMES


class NavigatorBrain(BaseModel):
    model_config = ConfigDict(extra="allow")

    evaluation_previous_goal: str = "Unknown"
    memory: str = ""
    next_goal: str = ""


class NavigatorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    current_state: NavigatorBrain = Field(default_factory=NavigatorBrain)
    action: list[dict[str, Any]] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    observation: str = ""
    done: bool = False
    challenges: str = ""
    next_steps: str = ""
    final_answer: str = ""
    reasoning: str = ""
    web_task: bool = True


class CriteriaCheckerOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    passed: bool = False
    evidence: str = ""
    reason: str = ""


class HitlDebriefOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    inferred_reason: str = ""
    goal_achieved: str = ""
    outcome: str = "unclear"
    evidence: str = ""
    remaining_work: str = ""
    confidence: str = "low"


class TaskExtractorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    task: str = ""
    name: str = ""


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _normalize_action_item(action: dict[str, Any]) -> dict[str, Any] | None:
    if "type" in action:
        action_type = action.get("type")
        if action_type not in ACTION_NAMES:
            return None
        args = {key: value for key, value in action.items() if key != "type"}
        return {action_type: args}
    if len(action) == 1:
        name, args = next(iter(action.items()))
        if name not in ACTION_NAMES:
            return None
        if not isinstance(args, dict):
            return {name: {}}
        return {name: args}
    return None


def validate_action_args(action_name: str, args: dict[str, Any]) -> dict[str, Any]:
    validated = dict(args)
    if action_name in {
        "click_element",
        "input_text",
        "get_dropdown_options",
        "select_dropdown_option",
    }:
        index = validated.get("index")
        if index is not None:
            validated["index"] = int(index)
    if action_name == "wait":
        if "seconds" in validated:
            validated["seconds"] = int(validated["seconds"])
        elif "duration" in validated:
            validated["seconds"] = int(validated["duration"])
    if action_name in {"switch_tab", "close_tab"} and "tab_id" in validated:
        validated["tab_id"] = int(validated["tab_id"])
    if action_name == "scroll_to_percent":
        if "yPercent" in validated:
            validated["yPercent"] = int(validated["yPercent"])
        elif "percent" in validated:
            validated["yPercent"] = int(validated["percent"])
    if action_name == "scroll_to_text" and "nth" in validated:
        validated["nth"] = int(validated["nth"])
    if action_name == "done" and "success" in validated:
        validated["success"] = _coerce_bool(validated["success"])
    return validated


def validate_navigator_output(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_actions = parsed.get("action", parsed.get("actions", []))
    if isinstance(raw_actions, dict):
        raw_actions = [raw_actions]
    if not isinstance(raw_actions, list):
        raw_actions = []

    normalized_actions: list[dict[str, Any]] = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_action_item(item)
        if normalized is None:
            continue
        action_name, action_args = next(iter(normalized.items()))
        try:
            normalized_actions.append(
                {action_name: validate_action_args(action_name, action_args)}
            )
        except (TypeError, ValueError):
            continue

    current_state = parsed.get("current_state", {})
    if not isinstance(current_state, dict):
        current_state = {}

    payload = {
        "current_state": current_state,
        "action": normalized_actions,
    }
    try:
        validated = NavigatorOutput.model_validate(payload)
    except ValidationError:
        return payload
    return validated.model_dump()


def validate_planner_output(parsed: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "observation": parsed.get("observation", ""),
        "done": _coerce_bool(parsed.get("done", False)),
        "challenges": parsed.get("challenges", ""),
        "next_steps": parsed.get("next_steps", ""),
        "final_answer": parsed.get("final_answer", ""),
        "reasoning": parsed.get("reasoning", ""),
        "web_task": _coerce_bool(parsed.get("web_task", True)),
    }
    try:
        validated = PlannerOutput.model_validate(payload)
    except ValidationError:
        return payload
    return validated.model_dump()


def validate_criteria_output(parsed: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "passed": _coerce_bool(parsed.get("passed", False)),
        "evidence": str(parsed.get("evidence", "") or ""),
        "reason": str(parsed.get("reason", "") or ""),
    }
    try:
        validated = CriteriaCheckerOutput.model_validate(payload)
    except ValidationError:
        return payload
    return validated.model_dump()


_VALID_HITL_OUTCOMES = frozenset({"achieved", "partial", "unclear", "failed"})
_VALID_HITL_CONFIDENCE = frozenset({"high", "medium", "low"})


def validate_hitl_debrief_output(parsed: dict[str, Any]) -> dict[str, Any]:
    outcome = str(parsed.get("outcome", "unclear") or "unclear").strip().lower()
    confidence = str(parsed.get("confidence", "low") or "low").strip().lower()
    payload = {
        "inferred_reason": str(parsed.get("inferred_reason", "") or ""),
        "goal_achieved": str(parsed.get("goal_achieved", "") or ""),
        "outcome": outcome if outcome in _VALID_HITL_OUTCOMES else "unclear",
        "evidence": str(parsed.get("evidence", "") or ""),
        "remaining_work": str(parsed.get("remaining_work", "") or ""),
        "confidence": confidence if confidence in _VALID_HITL_CONFIDENCE else "low",
    }
    if parsed.get("error"):
        payload["error"] = str(parsed["error"])
    try:
        validated = HitlDebriefOutput.model_validate(payload)
    except ValidationError:
        return payload
    return validated.model_dump()


def validate_task_extractor_output(parsed: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "task": str(parsed.get("task", "") or "").strip(),
        "name": str(parsed.get("name", "") or "").strip(),
    }
    try:
        validated = TaskExtractorOutput.model_validate(payload)
    except ValidationError:
        return payload
    return validated.model_dump()
