from __future__ import annotations

import logging
import time
from typing import Any

from ..agent.executor import Executor
from ..agent.history import AgentStepHistory
from ..agents.criteria_checker import CriteriaCheckerAgent
from ..agents.errors import (
    MaxFailuresReachedError,
    MaxStepsReachedError,
    RequestCancelledError,
)
from ..browser.context import BrowserContext
from ..config import normalize_browser_overrides
from ..main import create_llm
from .config_service import config_for_run
from .history_store import save_run_history
from .paths import REPORT_DIR, SCREENSHOT_DIR
from .replay_store import has_replay_script, load_run_replay, save_run_replay, delete_run_replay
from ..storage.websites import WebsiteStore
from .workers import local_browser_mode_enabled, worker_registry
from .step_mapper import (
    build_step_start,
    history_item_to_step,
    human_action_to_step,
    human_handoff_to_step,
    navigator_to_step,
)
from ..reporting import generate_run_report
from ..reporting.builder import build_action_timeline
from ..reporting.replay_executor import execute_replay_steps
from ..reporting.replay_script import build_replay_steps, count_skipped_actions, format_replay_script

log = logging.getLogger(__name__)


def _next_step_index(run: RunState) -> int:
    if not run.steps:
        return 1
    return max(int(step.get("index", 0)) for step in run.steps) + 1


def _resolve_step_index(run: RunState, event: dict[str, Any]) -> int:
    index = int(event.get("index") or 0)
    if index > 0:
        return index
    return _next_step_index(run)


def _upsert_step(run: RunState, step_data: dict[str, Any]) -> None:
    index = int(step_data.get("index", 0))
    if index <= 0:
        run.steps.append(step_data)
        return
    for position, step in enumerate(run.steps):
        if int(step.get("index", 0)) == index:
            run.steps[position] = step_data
            return
    run.steps.append(step_data)


def _capture_screenshot(browser_context: BrowserContext, run_id: str, step_index: int) -> str | None:
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{run_id[:8]}_step_{step_index}.png"
        path = SCREENSHOT_DIR / filename
        browser_context.get_current_page().save_screenshot_file(str(path))
        return f"/screenshots/{filename}"
    except Exception as exc:
        log.debug("Screenshot capture failed for run %s step %s: %s", run_id[:8], step_index, exc)
        return None


def _handle_event(run: RunState, browser_context: BrowserContext, event: dict[str, Any]) -> None:
    event_type = event.get("type")

    if event_type == "step_start":
        _upsert_step(run, event["step"])
    elif event_type == "step_end":
        step_data = dict(event["step"])
        screenshot_url = _capture_screenshot(browser_context, run.run_id, step_data.get("index", 0))
        if screenshot_url:
            step_data["screenshot_url"] = screenshot_url
        _upsert_step(run, step_data)
        event = {**event, "step": step_data}
    elif event_type == "plan_update":
        run.plan = event.get("plan", {})
    elif event_type == "tokens_update":
        run.tokens = int(event.get("tokens", 0))
        run.prompt_tokens = int(event.get("prompt_tokens", 0))
        run.completion_tokens = int(event.get("completion_tokens", 0))
        run.cache_tokens = int(event.get("cache_tokens", 0))
        run.cost_usd = event.get("cost_usd")
    elif event_type == "turn_timing":
        run.turn_timing = {
            "snapshot_ms": event.get("snapshot_ms"),
            "llm_navigator_ms": event.get("llm_navigator_ms"),
            "batch_ms": event.get("batch_ms"),
            "settle_ms": event.get("settle_ms"),
            "turn_ms": event.get("turn_ms"),
        }
    elif event_type == "done":
        run.status = event.get("status", run.status)
        run.summary = event.get("summary", "")
        run.finished_at = time.time()
    elif event_type == "status":
        run.status = event.get("status", run.status)
    elif event_type == "human_intervention_required":
        run.status = "awaiting_human"
        run.hitl_reason = str(event.get("reason", ""))
        run.hitl_source = str(event.get("source", ""))
        run.hitl_deadline = event.get("deadline")
    elif event_type == "human_control_started":
        run.human_controlling = True
    elif event_type == "human_intervention_ended":
        run.human_controlling = False
        run.hitl_reason = ""
        run.hitl_deadline = None
        run.status = "running"
    elif event_type == "human_action":
        step_index = _resolve_step_index(run, event)
        step_data = human_action_to_step(
            step_index,
            action=str(event.get("action", "")),
            args=dict(event.get("args") or {}),
            result=str(event.get("result", "")),
        )
        _upsert_step(run, step_data)
        event = {**event, "step": step_data}
    elif event_type == "human_handoff":
        step_index = _resolve_step_index(run, event)
        step_data = human_handoff_to_step(
            step_index,
            analysis=dict(event.get("analysis") or {}),
            actions=list(event.get("actions") or []),
            intervention_reason=str(event.get("intervention_reason", "")),
            intervention_source=str(event.get("intervention_source", "")),
            start_url=str(event.get("start_url", "")),
            end_url=str(event.get("end_url", "")),
        )
        _upsert_step(run, step_data)
        event = {**event, "step": step_data}

    run.broadcast(event)


def _generate_report(run: RunState, executor: Executor | None, config) -> None:
    if executor is None:
        return
    try:
        context = executor.context
        failed_actions = [
            {
                "url": record.url,
                "action": record.action_name,
                "args": record.action_args,
                "error": record.error,
            }
            for record in context.failed_actions
        ]
        planner_model = getattr(config, "planner_model", None) or config.active_model
        report_path = generate_run_report(
            run,
            context.history,
            llm_provider=getattr(config, "active_provider", None) or config.llm_provider,
            llm_model=config.active_model,
            planner_model=planner_model,
            failed_actions=failed_actions,
        )
        run.report_path = str(report_path)
        run.broadcast({
            "type": "report_ready",
            "report_path": f"/api/runs/{run.run_id}/report",
        })
        log.info("[run:%s] report written to %s", run.run_id[:8], report_path)
    except Exception as exc:
        log.warning("[run:%s] report generation failed: %s", run.run_id[:8], exc, exc_info=True)


def _set_terminal_status(run: RunState, status: str, summary: str) -> None:
    run.status = status
    run.summary = summary
    run.finished_at = time.time()
    run.broadcast({"type": "done", "status": status, "summary": summary})


def _apply_criteria_verdict(
    run: RunState,
    executor: Executor,
    llm,
) -> None:
    context = executor.context
    checker = CriteriaCheckerAgent(llm)
    state_message = CriteriaCheckerAgent.build_state_message(context)
    verdict = checker.check(
        task=run.task,
        success_criteria=run.success_criteria,
        state_message=state_message,
        final_answer=context.final_answer or "",
        test_name=run.name,
    )
    # Persist a truncated copy of what the grader saw for debugging false fails.
    preview = state_message.strip()
    if len(preview) > 4000:
        preview = preview[:4000] + "\n... [truncated]"
    if preview:
        verdict["observation_preview"] = preview
    run.criteria_verdict = verdict
    if verdict.get("passed"):
        summary = (
            verdict.get("reason")
            or verdict.get("evidence")
            or context.final_answer
            or "Success criteria met."
        )
        _set_terminal_status(run, "pass", str(summary))
        return

    summary = verdict.get("reason") or verdict.get("evidence") or "Success criteria not met."
    _set_terminal_status(run, "fail", str(summary))


def _save_run_replay_data(run: RunState, executor: Executor) -> None:
    history = executor.context.history
    if not history.history:
        return
    timeline = build_action_timeline(history)
    replay_steps = build_replay_steps(timeline)
    if not replay_steps:
        return
    skipped_failed, skipped_done = count_skipped_actions(timeline)
    replay_script = format_replay_script(
        replay_steps,
        run_id=run.run_id,
        status=run.status,
        skipped_failed=skipped_failed,
        skipped_done=skipped_done,
    )
    save_run_replay(run.run_id, replay_steps, replay_script)


def _script_replay_with_events(
    run: RunState,
    browser_context: BrowserContext,
    steps: list[dict[str, Any]],
    *,
    action_retry_wait_seconds: float = 0.0,
) -> list:
    from ..agent.context import ActionResult

    results: list[ActionResult] = []
    step_started_at = time.time()

    for index, step in enumerate(steps):
        _handle_event(
            run,
            browser_context,
            {
                "type": "step_start",
                "step": build_step_start(index + 1, f"Replay: {step.get('action', 'action')}"),
            },
        )
        step_started_at = time.time()

        batch_results = execute_replay_steps(
            browser_context,
            [step],
            action_retry_wait_seconds=action_retry_wait_seconds,
        )
        results.extend(batch_results)
        result = batch_results[0] if batch_results else ActionResult(error="No replay result")

        elapsed_ms = int((time.time() - step_started_at) * 1000)
        _handle_event(
            run,
            browser_context,
            {
                "type": "step_end",
                "step": {
                    "index": index + 1,
                    "thought": f"Replay step {index + 1}",
                    "action": step.get("action", ""),
                    "args": step.get("args") or {},
                    "result": result.extracted_content or result.error or "",
                    "status": "fail" if result.error else "pass",
                    "elapsed_ms": elapsed_ms,
                },
            },
        )

        if result.error:
            break

    return results


def _replay_with_events(
    run: RunState,
    executor: Executor,
    browser_context: BrowserContext,
    history: AgentStepHistory,
) -> list:
    step_started_at = time.time()

    def on_step(index: int, history_item, step_results) -> None:
        nonlocal step_started_at
        step_index = index + 1
        _handle_event(
            run,
            browser_context,
            {
                "type": "step_start",
                "step": build_step_start(step_index, "Replaying recorded actions…"),
            },
        )
        elapsed_ms = int((time.time() - step_started_at) * 1000)
        step = history_item_to_step(
            step_index,
            history_item,
            step_results,
            elapsed_ms=elapsed_ms,
        )
        _handle_event(run, browser_context, {"type": "step_end", "step": step})
        step_started_at = time.time()

    return executor.replay_history(
        history,
        skip_failures=False,
        on_step=on_step,
    )


def run_automation(run: RunState) -> None:
    browser_context: BrowserContext | None = None
    executor: Executor | None = None
    config = None
    replay_script_data: dict[str, Any] | None = None
    worker_browser_started = False

    try:
        run.status = "running"
        run.broadcast({"type": "status", "status": "running"})
        log.info("[run:%s] started — task: %s", run.run_id[:8], run.effective_task[:120])

        if run.use_replay_script and run.source_run_id:
            replay_script_data = load_run_replay(run.source_run_id)
            if replay_script_data is None:
                raise ValueError(
                    f"Replay script not found for source run {run.source_run_id}"
                )

        config = config_for_run()
        config.headless = run.headless
        config.max_steps = run.max_steps
        if run.fresh_profile is not None:
            effective_fresh = bool(run.fresh_profile)
        else:
            effective_fresh = bool(config.fresh_profile)

        registry = worker_registry()
        worker = registry.get(run.user_id)
        if worker is not None:
            chrome_user_data, chrome_profile_directory = registry.resolve_profile_for_start(
                run.user_id,
                chrome_user_data=config.chrome_user_data,
                chrome_profile_directory=config.chrome_profile_directory,
            )
            log.info(
                "[run:%s] starting Connect browser fresh=%s profile=%s/%s",
                run.run_id[:8],
                effective_fresh,
                chrome_user_data or "(app-default)",
                chrome_profile_directory or "-",
            )
            proxy_url = registry.request_browser_start(
                run.user_id,
                run_id=run.run_id,
                fresh_profile=effective_fresh,
                chrome_user_data=chrome_user_data,
                chrome_profile_directory=chrome_profile_directory,
            )
            worker_browser_started = True
            normalized_cdp = proxy_url
            normalized_fresh = effective_fresh
            config.cdp_url = normalized_cdp
            config.fresh_profile = normalized_fresh
            config.chrome_user_data = chrome_user_data
            config.chrome_profile_directory = chrome_profile_directory
            run.cdp_url = normalized_cdp
            run.fresh_profile = normalized_fresh
        elif local_browser_mode_enabled():
            effective_cdp = run.cdp_url or config.cdp_url
            normalized_cdp, normalized_fresh = normalize_browser_overrides(
                cdp_url=effective_cdp,
                fresh_profile=effective_fresh,
            )
            config.cdp_url = normalized_cdp
            config.fresh_profile = normalized_fresh
            run.cdp_url = normalized_cdp or None
            run.fresh_profile = normalized_fresh
        else:
            raise RuntimeError("Connect app offline")

        llm = create_llm(config)
        planner_provider = config.planner_llm_provider or config.llm_provider
        planner_llm = (
            create_llm(config, planner_provider)
            if planner_provider != config.llm_provider
            else llm
        )

        browser_context = BrowserContext(config)
        browser_context.launch(
            cdp_url=normalized_cdp or None,
            fresh_profile=normalized_fresh,
        )
        browser_context.new_page(config.home_page_url)

        step_started_at = time.time()

        def on_event(event: dict[str, Any]) -> None:
            nonlocal step_started_at
            if event.get("type") == "step_end" and browser_context is not None:
                elapsed_ms = int((time.time() - step_started_at) * 1000)
                nav_result = event.get("nav_result", {})
                metrics = event.get("metrics") or {}
                step = navigator_to_step(
                    event.get("index", len(run.steps)),
                    nav_result,
                    elapsed_ms=elapsed_ms,
                    metrics=metrics,
                )
                _handle_event(run, browser_context, {"type": "step_end", "step": step})
                step_started_at = time.time()
                return
            if event.get("type") == "step_start":
                step_started_at = time.time()
            _handle_event(run, browser_context, event)

        executor = Executor(
            run.effective_task,
            browser_context,
            llm,
            config,
            planner_llm=planner_llm,
            on_event=on_event,
            success_criteria=run.success_criteria,
        )
        run.executor = executor

        if replay_script_data is not None:
            executor.context.hitl_enabled = False

        if run._cancelled.is_set():
            _set_terminal_status(run, "cancelled", "Run cancelled before execution started.")
            return

        if replay_script_data is not None:
            browser_context.remove_highlight()
            replay_results = _script_replay_with_events(
                run,
                browser_context,
                replay_script_data.get("replay_steps") or [],
                action_retry_wait_seconds=config.replay_action_retry_wait_seconds,
            )
            if run.status == "cancelled" or run._cancelled.is_set():
                return
            _apply_criteria_verdict(run, executor, llm)
            return

        result = executor.execute()

        if run.status == "cancelled" or run._cancelled.is_set():
            return
        if executor.context.hitl_timed_out:
            return
        if result:
            _apply_criteria_verdict(run, executor, llm)
        else:
            _set_terminal_status(
                run,
                "error",
                run.summary or "Task did not complete within the step limit.",
            )

    except RequestCancelledError:
        if run.status != "cancelled":
            _set_terminal_status(run, "cancelled", "Run cancelled.")
    except (MaxStepsReachedError, MaxFailuresReachedError) as exc:
        if run.status != "cancelled":
            _set_terminal_status(run, "error", str(exc))
    except Exception as exc:
        if run.status != "cancelled":
            _set_terminal_status(run, "error", str(exc))
            run.broadcast({"type": "error", "message": str(exc)})
            log.error("[run:%s] error: %s", run.run_id[:8], exc, exc_info=True)
    finally:
        if run.finished_at is None:
            run.finished_at = time.time()
        if executor is not None:
            executor.flush_token_usage()
        # Drop the CDP mux before Playwright closes sockets so cleanup cannot
        # flood/kill the worker control WSS. Then stop Chrome only (WSS stays).
        # Release the lease before history/report so a consecutive run can start.
        if worker_browser_started:
            try:
                worker_registry().detach_cdp_proxy(run.user_id, run_id=run.run_id)
            except Exception as exc:
                log.warning("[run:%s] CDP proxy detach failed: %s", run.run_id[:8], exc)
        if executor is not None:
            try:
                executor.cleanup()
            except Exception:
                pass
        elif browser_context is not None:
            try:
                browser_context.close()
            except Exception:
                pass
        if worker_browser_started:
            try:
                worker_registry().request_browser_stop(
                    run.user_id,
                    run_id=run.run_id,
                    wait=True,
                    timeout=5.0,
                )
            except Exception as exc:
                log.warning("[run:%s] worker browser stop failed: %s", run.run_id[:8], exc)
        if run.status != "cancelled" and executor is not None:
            try:
                save_run_history(run.run_id, executor.context.history)
            except Exception as exc:
                log.warning("[run:%s] history save failed: %s", run.run_id[:8], exc)
            if not run.use_replay_script and run.status == "pass":
                try:
                    _save_run_replay_data(run, executor)
                except Exception as exc:
                    log.warning("[run:%s] replay save failed: %s", run.run_id[:8], exc)
                if (
                    run.website_id
                    and run.website_task_id
                    and has_replay_script(run.run_id)
                ):
                    try:
                        WebsiteStore(run.user_id).update_task(
                            run.website_id,
                            run.website_task_id,
                            last_trained_run_id=run.run_id,
                        )
                    except Exception as exc:
                        log.warning(
                            "[run:%s] task replay pointer update failed: %s",
                            run.run_id[:8],
                            exc,
                        )
            elif not run.use_replay_script:
                try:
                    delete_run_replay(run.run_id)
                except Exception as exc:
                    log.warning(
                        "[run:%s] stale replay cleanup failed: %s",
                        run.run_id[:8],
                        exc,
                    )
            _generate_report(run, executor, config)
        run.executor = None
        duration = time.time() - run.started_at
        log.info("[run:%s] finished status=%s duration=%.1fs", run.run_id[:8], run.status, duration)
        try:
            run.persist(has_replay_script=has_replay_script(run.run_id))
        except Exception as exc:
            log.warning("[run:%s] run persistence failed: %s", run.run_id[:8], exc)
        run.broadcast({"type": "closed"})
