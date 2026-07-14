from __future__ import annotations

import json
from typing import Any

from ..actions.builder import parse_actions
from ..agent.history import AgentStepHistory
from ..agent.messages.utils import fix_actions
from ..server.run_state import RunState
from .replay_script import (
    build_replay_steps,
    count_skipped_actions,
    format_replay_script,
)


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}m {remainder:.0f}s"


def _parse_actions(model_output: str | None) -> list[dict[str, Any]]:
    if not model_output:
        return []
    try:
        parsed = json.loads(model_output)
    except json.JSONDecodeError:
        return []
    raw_actions = fix_actions(parsed)
    actions = parse_actions(raw_actions, max_actions=20)
    return [{"name": action.name, "args": dict(action.args)} for action in actions]


def build_action_timeline(history: AgentStepHistory) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for step_index, record in enumerate(history.history, start=1):
        parsed_actions = _parse_actions(record.model_output)
        for action_index, result in enumerate(record.result, start=1):
            if action_index <= len(parsed_actions):
                action_name = parsed_actions[action_index - 1]["name"]
                action_args = parsed_actions[action_index - 1]["args"]
            else:
                action_name = result.action_name or "unknown"
                action_args = {"index": result.action_index} if result.action_index is not None else {}

            if action_name == "unknown" and not result.action_name:
                continue

            element = result.interacted_element
            if element is None and action_index - 1 < len(record.state.interacted_elements):
                element = record.state.interacted_elements[action_index - 1]
            element_dict: dict[str, Any] | None = None
            if element is not None and hasattr(element, "to_dict"):
                element_dict = element.to_dict()

            timeline.append(
                {
                    "step": step_index,
                    "action_num": action_index,
                    "url": record.state.url,
                    "page_title": record.state.title,
                    "action": result.action_name or action_name,
                    "args": action_args,
                    "executed": not bool(result.error),
                    "error": result.error,
                    "verification_status": result.verification_status,
                    "verification_evidence": result.verification_evidence,
                    "extracted_content": result.extracted_content,
                    "element": element_dict,
                }
            )
    return timeline


def build_report_data(
    run: RunState,
    history: AgentStepHistory,
    *,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    planner_model: str | None = None,
    failed_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    finished_at = run.finished_at or run.started_at
    duration_s = finished_at - run.started_at
    step_elapsed_ms = sum(int(step.get("elapsed_ms") or 0) for step in run.steps)
    timeline = build_action_timeline(history)
    replay_steps = build_replay_steps(timeline)
    skipped_failed, skipped_done = count_skipped_actions(timeline)

    return {
        "run_id": run.run_id,
        "task": run.task,
        "effective_task": run.effective_task,
        "website_id": run.website_id,
        "status": run.status,
        "summary": run.summary,
        "headless": run.headless,
        "max_steps": run.max_steps,
        "cdp_url": run.cdp_url,
        "fresh_profile": run.fresh_profile,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_s": duration_s,
        "duration_label": _format_duration(duration_s),
        "step_elapsed_ms": step_elapsed_ms,
        "tokens": {
            "total": run.tokens,
            "prompt": run.prompt_tokens,
            "completion": run.completion_tokens,
            "cache": run.cache_tokens,
            "cost_usd": run.cost_usd,
        },
        "turn_timing": run.turn_timing,
        "llm": {
            "provider": llm_provider,
            "model": llm_model,
            "planner_model": planner_model,
        },
        "plan": run.plan,
        "steps": run.steps,
        "action_timeline": timeline,
        "replay_steps": replay_steps,
        "replay_script": format_replay_script(
            replay_steps,
            run_id=run.run_id,
            status=run.status,
            skipped_failed=skipped_failed,
            skipped_done=skipped_done,
        ),
        "failed_actions": failed_actions or [],
    }
