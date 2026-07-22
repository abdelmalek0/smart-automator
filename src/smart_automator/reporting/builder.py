from __future__ import annotations

import base64
import json
import re
from pathlib import Path
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


_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_WEBSITE_RE = re.compile(r"^Website:\s*(.+?)\s*\((https?://[^)]+)\)\s*$", re.MULTILINE)


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

            source = None
            if record.metadata and record.metadata.get("source"):
                source = record.metadata["source"]

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
                    "source": source,
                }
            )
    return timeline


def group_timeline_by_step(timeline: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for entry in timeline:
        step_num = int(entry.get("step") or 0)
        grouped.setdefault(step_num, []).append(entry)
    return grouped


def _extract_block(text: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def extract_run_context(
    task: str,
    effective_task: str,
    website_id: str | None,
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    website_name: str | None = None
    website_url: str | None = None
    context_prompt: str | None = None
    task_only = task.strip()

    match = _WEBSITE_RE.search(effective_task)
    if match:
        website_name = match.group(1).strip()
        website_url = match.group(2).strip()

    context_prompt = _extract_block(effective_task, "Context")
    parsed_task = _extract_block(effective_task, "Task")
    if parsed_task:
        task_only = parsed_task

    detected_urls = _URL_RE.findall(task) if not website_url else []

    start_url: str | None = None
    for entry in timeline:
        if entry.get("action") == "go_to_url":
            url = (entry.get("args") or {}).get("url")
            if url:
                start_url = str(url)
                break
        if entry.get("url"):
            start_url = str(entry["url"])
            break

    return {
        "website_id": website_id,
        "website_name": website_name,
        "website_url": website_url or start_url,
        "context_prompt": context_prompt,
        "task_only": task_only,
        "detected_urls": detected_urls,
        "start_url": start_url,
    }


def embed_step_screenshots(
    steps: list[dict[str, Any]],
    screenshot_dir: Path,
) -> list[dict[str, Any]]:
    embedded: list[dict[str, Any]] = []
    for step in steps:
        step_copy = dict(step)
        screenshot_url = step_copy.get("screenshot_url")
        screenshot_src: str | None = None
        screenshot_missing = False

        if screenshot_url and isinstance(screenshot_url, str):
            filename = screenshot_url.rsplit("/", 1)[-1]
            path = screenshot_dir / filename
            if path.is_file():
                encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")
                screenshot_src = f"data:image/png;base64,{encoded}"
            else:
                screenshot_missing = True
                screenshot_src = screenshot_url

        step_copy["screenshot_src"] = screenshot_src
        step_copy["screenshot_missing"] = screenshot_missing
        embedded.append(step_copy)
    return embedded


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
    context = extract_run_context(
        run.task,
        run.effective_task,
        run.website_id,
        timeline,
    )

    return {
        "run_id": run.run_id,
        "name": run.name,
        "task": run.task,
        "success_criteria": run.success_criteria,
        "source_run_id": run.source_run_id,
        "effective_task": run.effective_task,
        "website_id": run.website_id,
        **context,
        "status": run.status,
        "summary": run.summary,
        "criteria_verdict": run.criteria_verdict,
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
            "input": run.prompt_tokens,
            "output": run.completion_tokens,
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
        "timeline_by_step": group_timeline_by_step(timeline),
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
