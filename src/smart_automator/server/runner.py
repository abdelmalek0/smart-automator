from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from ..agent.executor import Executor
from ..agents.errors import (
    MaxFailuresReachedError,
    MaxStepsReachedError,
    RequestCancelledError,
)
from ..browser.context import BrowserContext
from ..main import create_llm
from .config_service import config_for_run
from .paths import REPORT_DIR, SCREENSHOT_DIR
from .run_state import RunState
from .step_mapper import navigator_to_step
from ..reporting import generate_run_report

log = logging.getLogger(__name__)


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
        run.steps.append(event["step"])
    elif event_type == "step_end":
        step_data = dict(event["step"])
        screenshot_url = _capture_screenshot(browser_context, run.run_id, step_data.get("index", 0))
        if screenshot_url:
            step_data["screenshot_url"] = screenshot_url
        idx = int(step_data.get("index", 0)) - 1
        if 0 <= idx < len(run.steps):
            run.steps[idx] = step_data
        elif run.steps:
            run.steps[-1] = step_data
        else:
            run.steps.append(step_data)
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


def run_automation(run: RunState) -> None:
    browser_context: BrowserContext | None = None
    executor: Executor | None = None
    config = None

    try:
        run.status = "running"
        run.broadcast({"type": "status", "status": "running"})
        log.info("[run:%s] started — task: %s", run.run_id[:8], run.effective_task[:120])

        config = config_for_run()
        config.headless = run.headless
        config.max_steps = run.max_steps
        if run.cdp_url:
            config.cdp_url = run.cdp_url
        if run.fresh_profile:
            config.fresh_profile = True

        llm = create_llm(config)
        planner_provider = config.planner_llm_provider or config.llm_provider
        planner_llm = (
            create_llm(config, planner_provider)
            if planner_provider != config.llm_provider
            else llm
        )

        browser_context = BrowserContext(config)
        browser_context.launch(
            cdp_url=run.cdp_url,
            fresh_profile=run.fresh_profile,
        )
        browser_context.new_page(config.home_page_url)

        step_started_at = time.time()

        def on_event(event: dict[str, Any]) -> None:
            nonlocal step_started_at
            if event.get("type") == "step_end" and browser_context is not None:
                elapsed_ms = int((time.time() - step_started_at) * 1000)
                nav_result = event.get("nav_result", {})
                step = navigator_to_step(
                    event.get("index", len(run.steps)),
                    nav_result,
                    elapsed_ms=elapsed_ms,
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
        )
        run.executor = executor

        if run._cancelled.is_set():
            run.status = "cancelled"
            run.summary = "Run cancelled before execution started."
            run.finished_at = time.time()
            run.broadcast({"type": "done", "status": "cancelled", "summary": run.summary})
            return

        result = executor.execute()

        if run.status == "cancelled":
            pass
        elif result:
            run.status = "pass"
            run.summary = result
            run.finished_at = time.time()
            run.broadcast({"type": "done", "status": "pass", "summary": run.summary})
        else:
            run.status = "fail"
            run.summary = run.summary or "Task did not complete within the step limit."
            run.finished_at = time.time()
            run.broadcast({"type": "done", "status": "fail", "summary": run.summary})

    except RequestCancelledError:
        if run.status != "cancelled":
            run.status = "cancelled"
            run.summary = "Run cancelled."
            run.finished_at = time.time()
            run.broadcast({"type": "done", "status": "cancelled", "summary": run.summary})
    except (MaxStepsReachedError, MaxFailuresReachedError) as exc:
        if run.status != "cancelled":
            run.status = "fail"
            run.summary = str(exc)
            run.finished_at = time.time()
            run.broadcast({"type": "done", "status": "fail", "summary": run.summary})
    except Exception as exc:
        if run.status != "cancelled":
            run.status = "error"
            run.summary = str(exc)
            run.finished_at = time.time()
            run.broadcast({"type": "error", "message": str(exc)})
            run.broadcast({"type": "done", "status": "error", "summary": run.summary})
            log.error("[run:%s] error: %s", run.run_id[:8], exc, exc_info=True)
    finally:
        if run.finished_at is None:
            run.finished_at = time.time()
        if executor is not None:
            executor.flush_token_usage()
        _generate_report(run, executor, config)
        run.executor = None
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
        duration = time.time() - run.started_at
        log.info("[run:%s] finished status=%s duration=%.1fs", run.run_id[:8], run.status, duration)
        run.broadcast({"type": "closed"})
