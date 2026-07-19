from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable

from rich.console import Console
from rich.panel import Panel

from ..actions.builder import ActionBuilder
from ..agents.action_critic import ActionCriticAgent
from ..agents.errors import (
    ChatModelAuthError,
    ChatModelBadRequestError,
    ChatModelForbiddenError,
    MaxFailuresReachedError,
    MaxStepsReachedError,
    RequestCancelledError,
    classify_llm_error,
)
from ..agents.navigator import MAX_CONSECUTIVE_NO_ACTION_STEPS, NavigatorAgent
from ..agents.planner import PlannerAgent
from ..browser.views import URLNotAllowedError
from ..config import Config
from ..llm.base import BaseLLM
from .context import AgentContext, AgentOptions, AgentStepInfo
from .history import AgentStepHistory
from .messages.service import MessageManager, MessageManagerSettings
from ..agent.stuck_recovery import (
    build_premature_done_rejection_hint,
    build_stuck_recovery_hint,
    detect_stuck_signals,
    should_block_navigator_done,
    update_page_progress,
)
from ..server.step_mapper import build_step_start, planner_to_plan
from ..server.config_service import compute_cost_usd

console = Console()


def _format_planner_panel(plan: dict) -> str:
    lines: list[str] = []
    for key in ("observation", "reasoning", "challenges", "next_steps"):
        value = plan.get(key)
        if value:
            label = key.replace("_", " ").title()
            lines.append(f"[bold]{label}:[/bold] {value}")
    if "done" in plan:
        if plan.get("done"):
            lines.append("[bold green]Planner confirms done[/bold green]")
            if plan.get("final_answer"):
                lines.append(f"[bold]Final answer:[/bold] {plan['final_answer']}")
        else:
            lines.append("[bold yellow]Planner: not done yet[/bold yellow]")
    return "\n\n".join(lines) if lines else "(no planner output)"


def _format_navigator_panel(nav_result: dict) -> str:
    lines: list[str] = []
    current_state = nav_result.get("current_state") or {}
    for key in ("evaluation_previous_goal", "memory", "next_goal"):
        value = current_state.get(key)
        if value:
            label = key.replace("_", " ").title()
            lines.append(f"[bold]{label}:[/bold] {value}")

    actions = nav_result.get("actions") or []
    if actions:
        lines.append("[bold]Actions:[/bold]")
        if nav_result.get("auto_wait"):
            streak = nav_result.get("consecutive_no_action_steps", 0)
            lines.append(
                f"[dim]Auto-wait injected ({streak}/{MAX_CONSECUTIVE_NO_ACTION_STEPS} "
                "consecutive no-action steps).[/dim]"
            )
        if nav_result.get("requested_done"):
            lines.append(
                "[dim yellow]Navigator requested done — awaiting planner confirmation[/dim yellow]"
            )
        if nav_result.get("done_blocked"):
            lines.append(
                "[dim yellow]done action blocked — task not verified on current page[/dim yellow]"
            )
        for action in actions:
            lines.append(f"  • {action.name}: {json.dumps(action.args, ensure_ascii=False)}")

    metrics = nav_result.get("metrics")
    if metrics:
        lines.append(
            "[dim]"
            f"dom={metrics.get('dom_ms')}ms "
            f"llm={metrics.get('llm_ms')}ms "
            f"batch={metrics.get('batch_ms')}ms "
            f"settle={metrics.get('settle_ms')}ms "
            f"prompt={metrics.get('prompt_chars')}ch "
            f"obs={metrics.get('observation_chars', '?')}ch "
            f"highlights={metrics.get('num_highlights')} "
            f"recovery={metrics.get('recovery_attempts', 0)}"
            "[/dim]"
        )
    return "\n\n".join(lines) if lines else "(no navigator output)"


class Executor:
    def __init__(
        self,
        task: str,
        browser_context,
        llm: BaseLLM,
        config: Config,
        planner_llm: BaseLLM | None = None,
        on_event: Callable[[dict], None] | None = None,
        success_criteria: str = "",
    ):
        self._task = task
        self._tasks = [task]
        self._config = config
        self._llm = llm
        self._planner_llm = planner_llm or llm
        self._on_event = on_event
        self._success_criteria = success_criteria.strip()

        message_manager = MessageManager(
            MessageManagerSettings(max_input_tokens=config.max_input_tokens)
        )
        options = AgentOptions(
            max_steps=config.max_steps,
            max_actions_per_step=config.max_actions_per_step,
            max_failures=config.max_failures,
            max_input_tokens=config.max_input_tokens,
            planning_interval=config.planning_interval,
            include_attributes=config.include_attributes,
            action_delay_seconds=config.action_delay_seconds,
            replay_action_retry_wait_seconds=config.replay_action_retry_wait_seconds,
            replay_show_highlights=config.replay_show_highlights,
            max_observation_elements=config.max_observation_elements,
            max_observation_chars=config.max_observation_chars,
        )
        self._context = AgentContext(
            task_id=str(uuid.uuid4()),
            browser_context=browser_context,
            message_manager=message_manager,
            options=options,
        )
        self._context.success_criteria = self._success_criteria
        self._last_error: str | None = None

        self._llm.set_cancel_event(self._context.cancel_event)
        self._planner_llm.set_cancel_event(self._context.cancel_event)

        action_registry = ActionBuilder(self._context).build_default_actions()
        self._navigator = NavigatorAgent(llm, self._context, message_manager, action_registry)
        self._planner = PlannerAgent(self._planner_llm, self._context, message_manager)
        self._action_critic = ActionCriticAgent(llm, message_manager, context=self._context)

        message_manager.init_task_messages(
            self._navigator._system_prompt,
            task,
            success_criteria=self._success_criteria,
        )

    @property
    def context(self) -> AgentContext:
        return self._context

    def _emit(self, event: dict) -> None:
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass

    def _llm_usage_sources(self) -> list[tuple[BaseLLM, str, str]]:
        navigator_provider = self._config.active_provider or self._config.llm_provider
        navigator_model = self._config.active_model or self._llm.model_name or ""
        planner_provider = self._config.planner_llm_provider or navigator_provider
        planner_model = (
            getattr(self._config, "planner_model", None)
            or self._planner_llm.model_name
            or navigator_model
        )
        seen: dict[int, tuple[BaseLLM, str, str]] = {}
        for llm, provider, model in (
            (self._llm, navigator_provider, navigator_model),
            (self._planner_llm, planner_provider, planner_model),
        ):
            seen[id(llm)] = (llm, provider, model)
        return list(seen.values())

    def _emit_tokens(self) -> None:
        total = self._context.message_manager.history.total_tokens
        prompt_tokens = 0
        completion_tokens = 0
        cache_tokens = 0
        cost_parts: list[float | None] = []
        for llm, provider, model in self._llm_usage_sources():
            usage = llm.get_accumulated_usage()
            llm_prompt = usage.get("prompt_tokens", 0)
            llm_completion = usage.get("completion_tokens", 0)
            llm_cache = usage.get("cache_tokens", 0)
            prompt_tokens += llm_prompt
            completion_tokens += llm_completion
            cache_tokens += llm_cache
            cost_parts.append(
                compute_cost_usd(
                    provider,
                    model,
                    prompt_tokens=llm_prompt,
                    completion_tokens=llm_completion,
                    cache_tokens=llm_cache,
                )
            )
        if prompt_tokens == 0 and completion_tokens == 0:
            prompt_tokens = total
        tokens = prompt_tokens + completion_tokens
        if any(part is not None for part in cost_parts):
            cost_usd = sum(part or 0.0 for part in cost_parts)
        else:
            cost_usd = None
        self._emit(
            {
                "type": "tokens_update",
                "tokens": tokens or total,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_tokens": cache_tokens,
                "cost_usd": cost_usd,
            }
        )

    def flush_token_usage(self) -> None:
        """Emit a cumulative token snapshot for all LLM calls so far."""
        self._emit_tokens()

    def add_follow_up_task(self, task: str) -> None:
        self._tasks.append(task)
        self._context.message_manager.add_new_task(task)
        self._context.action_results = [
            result for result in self._context.action_results if result.include_in_memory
        ]

    def execute(self) -> str | None:
        context = self._context
        context.n_steps = 0
        latest_plan = None
        navigator_done = False
        step = 0

        try:
            for step in range(context.options.max_steps):
                context.step_info = AgentStepInfo(
                    step_number=context.n_steps,
                    max_steps=context.options.max_steps,
                )

                if self._should_stop():
                    break

                if context.n_steps % context.options.planning_interval == 0 or navigator_done:
                    navigator_done = False
                    latest_plan = self._run_planner()
                    if self._is_non_web_task_complete(latest_plan):
                        return context.final_answer
                    if self._check_task_completion(latest_plan):
                        return context.final_answer
                    if self._should_skip_navigation(latest_plan):
                        continue

                navigator_requested_done = False
                nav_outcome = self._navigate()
                if nav_outcome == "complete":
                    return context.final_answer
                if nav_outcome == "requested_done":
                    navigator_requested_done = True
                    latest_plan = self._run_planner()
                    if self._check_task_completion(latest_plan):
                        return context.final_answer
                    self._reject_premature_done(latest_plan)

            if latest_plan and latest_plan.get("result", {}).get("done"):
                return context.final_answer
            if step >= context.options.max_steps - 1 and not context.stopped:
                raise MaxStepsReachedError("Maximum execution steps reached")
            if context.stopped:
                return None
            return None
        except (
            URLNotAllowedError,
            ChatModelAuthError,
            ChatModelBadRequestError,
            ChatModelForbiddenError,
            RequestCancelledError,
            MaxStepsReachedError,
            MaxFailuresReachedError,
        ):
            raise
        finally:
            context.browser_context.remove_highlight()

    def replay_history(
        self,
        history: AgentStepHistory,
        *,
        max_retries: int = 3,
        skip_failures: bool = True,
        delay_between_actions: float = 2.0,
        on_step: Callable[[int, Any, list], None] | None = None,
    ) -> list:
        from ..agent.context import ActionResult

        results: list[ActionResult] = []
        if not history.history:
            raise ValueError("History is empty")

        self._context.browser_context.remove_highlight()

        for index, history_item in enumerate(history.history):
            if self._context.stopped:
                break
            step_results = self._navigator.execute_history_step(
                history_item,
                index,
                len(history.history),
                max_retries=max_retries,
                delay_seconds=delay_between_actions,
                skip_failures=skip_failures,
            )
            results.extend(step_results)
            if on_step is not None:
                on_step(index, history_item, step_results)
            if self._context.stopped:
                break
            if any(result.error for result in step_results):
                break
        return results

    def _check_task_completion(self, plan_output: dict | None) -> bool:
        result = plan_output.get("result") if plan_output else None
        if result and result.get("done"):
            if result.get("final_answer"):
                self._context.final_answer = result["final_answer"]
            self._context.consecutive_unvalidated_done = 0
            self._context.stuck_episode_active = False
            return True
        return False

    def _is_non_web_task_complete(self, plan_output: dict | None) -> bool:
        result = plan_output.get("result") if plan_output else None
        if not result or result.get("web_task", True):
            return False
        if result.get("done"):
            self._context.final_answer = result.get("final_answer", "")
            return True
        return False

    def _should_skip_navigation(self, plan_output: dict | None) -> bool:
        result = plan_output.get("result") if plan_output else None
        return bool(result and not result.get("web_task", True))

    def _reject_premature_done(self, plan_output: dict | None) -> None:
        self._context.consecutive_unvalidated_done += 1
        self._context.stuck_episode_active = True
        plan_result = plan_output.get("result") if plan_output else None
        self._context.message_manager.add_message_with_tokens({
            "role": "user",
            "content": build_premature_done_rejection_hint(plan_result),
        })

    def _run_planner(self) -> dict | None:
        context = self._context
        try:
            context.check_cancelled()
            position_for_plan = 0
            if len(self._tasks) > 1 or context.n_steps > 0:
                self._navigator.add_state_message_to_memory(
                    show_highlights=False,
                    wait_for_stable=False,
                )
                position_for_plan = context.message_manager.length() - 1
            else:
                position_for_plan = context.message_manager.length()

            console.print(
                Panel(
                    "[dim]Planning…[/dim]",
                    title=f"Planner (step {context.n_steps + 1})",
                    border_style="magenta",
                )
            )
            plan_output = self._planner.execute()
            self._navigator.remove_last_state_message_from_memory()
            if plan_output.get("result"):
                result = plan_output["result"]
                context.message_manager.add_plan(
                    json.dumps(result),
                    position_for_plan,
                )
                self._emit({"type": "plan_update", "plan": planner_to_plan(result)})
                self._emit_tokens()
                console.print(
                    Panel(
                        _format_planner_panel(result),
                        title="Planner",
                        border_style="magenta",
                    )
                )
            context.consecutive_failures = 0
            return plan_output
        except URLNotAllowedError:
            raise
        except RequestCancelledError:
            raise
        except Exception as error:
            classified = classify_llm_error(error) if isinstance(error, Exception) else error
            if isinstance(
                classified,
                (ChatModelAuthError, ChatModelBadRequestError, ChatModelForbiddenError, RequestCancelledError),
            ):
                raise classified
            context.consecutive_failures += 1
            if context.consecutive_failures >= context.options.max_failures:
                raise MaxFailuresReachedError("Max planner failures reached") from error
            return None

    def _inject_stuck_recovery_hint(self, signals, diagnostics: dict | None) -> None:
        self._context.message_manager.add_message_with_tokens(
            {"role": "user", "content": build_stuck_recovery_hint(signals, diagnostics)},
        )

    def _run_action_critic(self, signals) -> None:
        context = self._context
        reason = "; ".join(signals.reasons) if signals.reasons else "navigator stuck"
        console.print(
            Panel(
                "[dim]Running one-shot action critic…[/dim]",
                title="Action critic",
                border_style="yellow",
            )
        )
        suggestion = self._action_critic.suggest_actions(reason)
        self._emit_tokens()
        if not suggestion:
            return
        if not suggestion.get("actions"):
            if suggestion.get("error"):
                context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": ActionCriticAgent.format_critic_hint(suggestion),
                })
            return
        context.message_manager.add_message_with_tokens({
            "role": "user",
            "content": ActionCriticAgent.format_critic_hint(suggestion),
        })
        context.critic_runs_this_episode += 1
        console.print(
            Panel(
                suggestion.get("raw_preview", "(critic suggested actions)"),
                title="Action critic",
                border_style="yellow",
            )
        )

    def _handle_stuck_recovery(self, result: dict) -> bool:
        metrics = self._context.last_step_metrics or {}
        num_highlights = int(metrics.get("num_highlights", result.get("num_highlights", 0)))
        stale_steps = update_page_progress(
            self._context,
            url=result.get("page_url", ""),
            title=result.get("page_title", ""),
            action_errors=any(
                action_result.error for action_result in result.get("action_results", [])
            ),
            auto_wait=bool(result.get("auto_wait")),
            submit_hint_fired=bool(result.get("submit_hint_fired")),
            only_wait_actions=bool(result.get("only_wait_actions")),
            only_done_action=bool(result.get("only_done_action")),
        )
        signals = detect_stuck_signals(
            self._context,
            auto_wait=bool(result.get("auto_wait")),
            consecutive_no_action_steps=int(result.get("consecutive_no_action_steps", 0)),
            num_highlights=num_highlights,
            submit_hint_fired=bool(result.get("submit_hint_fired")),
            action_results=result.get("action_results", []),
            stale_steps_on_same_page=stale_steps,
            verification_issues=int(result.get("verification_issues", 0)),
        )
        if result.get("escalate_recovery"):
            signals.auto_wait_with_elements = num_highlights > 0
            signals.consecutive_no_action_steps = max(
                signals.consecutive_no_action_steps,
                MAX_CONSECUTIVE_NO_ACTION_STEPS,
            )
            signals.reasons.append("repeated no-action responses — escalating recovery")
            self._context.stuck_episode_active = True

        if not signals.needs_planner_recovery and not result.get("escalate_recovery"):
            return False

        self._inject_stuck_recovery_hint(signals, result.get("diagnostics"))
        plan_output = self._run_planner()
        if self._check_task_completion(plan_output):
            return True

        if signals.needs_action_critic(self._context.critic_runs_this_episode):
            self._run_action_critic(signals)
        return False

    def _navigate(self) -> str | None:
        context = self._context
        try:
            context.check_cancelled()
            if context.paused or context.stopped:
                return None

            console.print(
                Panel(
                    "[dim]Observing page and choosing actions…[/dim]",
                    title=f"Navigator (step {context.n_steps + 1})",
                    border_style="cyan",
                )
            )
            step_index = context.n_steps + 1
            self._emit({"type": "step_start", "step": build_step_start(step_index)})
            nav_started = time.time()
            nav_output = self._navigator.execute()
            if context.paused or context.stopped:
                return None

            if nav_output.get("error"):
                raise RuntimeError(nav_output["error"])

            result = nav_output.get("result", {})
            context.n_steps += 1
            if result:
                metrics = context.last_step_metrics
                nav_display = dict(result)
                if metrics:
                    nav_display["metrics"] = metrics
                self._emit(
                    {
                        "type": "step_end",
                        "index": step_index,
                        "nav_result": result,
                        "metrics": metrics,
                    }
                )
                self._emit_tokens()
                if metrics:
                    self._emit(
                        {
                            "type": "turn_timing",
                            "snapshot_ms": metrics.get("dom_ms"),
                            "llm_navigator_ms": metrics.get("llm_ms"),
                            "batch_ms": metrics.get("batch_ms"),
                            "settle_ms": metrics.get("settle_ms"),
                            "turn_ms": int((time.time() - nav_started) * 1000),
                        }
                    )
                console.print(
                    Panel(
                        _format_navigator_panel(nav_display),
                        title="Navigator",
                        border_style="cyan",
                    )
                )

            context.consecutive_failures = 0

            if result and self._handle_stuck_recovery(result):
                if self._context.final_answer:
                    return "complete"
                return None

            if result.get("requested_done"):
                return "requested_done"
            return None
        except URLNotAllowedError:
            raise
        except RequestCancelledError:
            raise
        except RuntimeError:
            raise
        except Exception as error:
            classified = classify_llm_error(error) if isinstance(error, Exception) else error
            if isinstance(
                classified,
                (ChatModelAuthError, ChatModelBadRequestError, ChatModelForbiddenError, RequestCancelledError),
            ):
                raise classified
            self._last_error = str(error)
            context.consecutive_failures += 1
            if context.consecutive_failures >= context.options.max_failures:
                raise MaxFailuresReachedError(
                    f"Max navigator failures reached: {self._last_error}"
                ) from error
            return False

    def _should_stop(self) -> bool:
        if self._context.stopped:
            return True
        while self._context.paused:
            time.sleep(0.2)
            if self._context.stopped:
                return True
        if self._context.consecutive_failures >= self._context.options.max_failures:
            return True
        return False

    def cancel(self):
        self._context.stop()

    def pause(self):
        self._context.pause()

    def resume(self):
        self._context.resume()

    def cleanup(self):
        self._context.browser_context.close()
