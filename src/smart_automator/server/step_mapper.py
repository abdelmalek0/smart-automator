from __future__ import annotations

from typing import Any

from ..actions.schemas import Action
from ..agent.compound_integrity import (
    format_action_results_with_verification,
    format_all_actions_args,
)


def planner_to_plan(plan_result: dict[str, Any]) -> dict[str, Any]:
    next_steps = plan_result.get("next_steps")
    remaining: list[str] = []
    if isinstance(next_steps, str) and next_steps.strip():
        remaining = [line.strip() for line in next_steps.split("\n") if line.strip()]
    elif isinstance(next_steps, list):
        remaining = [str(item) for item in next_steps if str(item).strip()]

    in_progress = plan_result.get("observation") or plan_result.get("reasoning") or ""
    completed: list[str] = []
    if plan_result.get("done"):
        answer = plan_result.get("final_answer")
        if answer:
            completed.append(str(answer))

    return {
        "completed": completed,
        "remaining": remaining,
        "skipped": [],
        "in_progress": in_progress or None,
    }


def build_step_start(index: int, thought: str = "Observing page and choosing actions…") -> dict[str, Any]:
    return {
        "index": index,
        "thought": thought,
        "action": "",
        "args": {},
        "result": "",
        "status": "running",
        "screenshot_url": None,
        "elapsed_ms": 0,
    }


def navigator_to_step(
    index: int,
    nav_result: dict[str, Any],
    *,
    screenshot_url: str | None = None,
    elapsed_ms: int = 0,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_state = nav_result.get("current_state") or {}
    thought = (
        current_state.get("next_goal")
        or current_state.get("memory")
        or current_state.get("evaluation_previous_goal")
        or ""
    )
    actions = nav_result.get("actions") or []
    if len(actions) > 1:
        action_name = ", ".join(action.name for action in actions)
    elif actions:
        action_name = actions[0].name
    else:
        action_name = "wait"

    action_results = nav_result.get("action_results") or []
    has_error = any(getattr(r, "error", None) for r in action_results)
    status = "fail" if has_error else "pass"
    if nav_result.get("error"):
        status = "error"

    turn_timing: dict[str, float | int] | None = None
    if metrics:
        turn_timing = {
            "snapshot_ms": metrics.get("dom_ms"),
            "llm_navigator_ms": metrics.get("llm_ms"),
            "batch_ms": metrics.get("batch_ms"),
            "settle_ms": metrics.get("settle_ms"),
        }

    return {
        "index": index,
        "thought": str(thought),
        "action": action_name,
        "args": format_all_actions_args(actions),
        "result": format_action_results_with_verification(action_results),
        "status": status,
        "screenshot_url": screenshot_url,
        "elapsed_ms": elapsed_ms,
        "turn_timing": turn_timing,
    }


def compose_task(task: str, *, name: str, url: str, context_prompt: str) -> str:
    parts: list[str] = []
    if url.strip():
        parts.append(f"Website: {name} ({url.strip()})")
    if context_prompt.strip():
        parts.append(f"Context: {context_prompt.strip()}")
    parts.append(f"Task: {task.strip()}")
    return "\n\n".join(parts)
