from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable

from rich.console import Console
from rich.panel import Panel

from ..actions.builder import ActionBuilder
from ..agents.criteria_checker import CriteriaCheckerAgent
from ..agents.hitl_debrief import HitlDebriefAgent
from ..agents.errors import (
    ChatModelAuthError,
    ChatModelBadRequestError,
    ChatModelForbiddenError,
    HitlInterruptedError,
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
from ..agents.action_critic import ActionCriticAgent
from .context import AgentContext, AgentOptions, AgentStepInfo
from .history import AgentStepHistory
from .hitl import HitlController
from .messages.service import MessageManager, MessageManagerSettings
from ..agent.stuck_recovery import (
    build_premature_done_rejection_hint,
    build_stuck_recovery_hint,
    detect_stuck_signals,
    update_page_progress,
)
from ..agent.log_utils import log_section
from ..server.step_mapper import build_step_start, planner_to_plan
from ..server.config_service import compute_cost_usd

console = Console()
log = logging.getLogger(__name__)


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
        run_id: str = "",
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
            hitl_timeout_seconds=float(config.hitl_timeout_minutes) * 60.0,
            max_unvalidated_dones=config.max_unvalidated_dones,
        )
        self._context = AgentContext(
            task_id=str(uuid.uuid4()),
            browser_context=browser_context,
            message_manager=message_manager,
            options=options,
        )
        self._context.run_id = run_id
        self._context.success_criteria = self._success_criteria
        self._context.hitl_enabled = not config.headless
        self._last_error: str | None = None
        self._last_nav_result: dict | None = None
        self._hitl = HitlController(self._context, emit=self._emit)

        self._llm.set_cancel_event(self._context.cancel_event)
        self._planner_llm.set_cancel_event(self._context.cancel_event)
        interrupt_check = lambda: self._context.hitl_interrupt
        self._llm.set_interrupt_check(interrupt_check)
        self._planner_llm.set_interrupt_check(interrupt_check)

        action_registry = ActionBuilder(self._context).build_default_actions()
        self._navigator = NavigatorAgent(llm, self._context, message_manager, action_registry)
        self._planner = PlannerAgent(self._planner_llm, self._context, message_manager)
        self._action_critic = ActionCriticAgent(
            self._planner_llm, message_manager, context=self._context
        )
        self._hitl_debrief = HitlDebriefAgent(
            self._planner_llm,
            message_manager,
            context=self._context,
        )

        message_manager.init_task_messages(
            self._navigator._system_prompt,
            task,
            success_criteria=self._success_criteria,
        )

    @property
    def context(self) -> AgentContext:
        return self._context

    def _run_prefix(self) -> str:
        run_id = self._context.run_id
        if run_id:
            return f"[run:{run_id[:8]}] "
        return ""

    def _log_section(self, title: str) -> None:
        log_section(log, self._run_prefix(), title)

    @property
    def hitl(self) -> HitlController:
        return self._hitl

    def submit_hitl_command(
        self,
        action: str,
        *,
        wait: bool = True,
        **kwargs: Any,
    ) -> tuple[bool, str | None]:
        return self._hitl.submit_command(action, wait=wait, **kwargs)

    def _emit(self, event: dict) -> None:
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass

    @staticmethod
    def _config_str(value: object) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def _llm_billing_identity(
        self,
        llm: BaseLLM,
        *,
        fallback_provider: str,
        fallback_model: str,
    ) -> tuple[str, str]:
        provider = self._config_str(llm.billing_provider) or fallback_provider
        model = self._config_str(llm.model_name or "") or fallback_model
        return provider, model

    def _llm_usage_entries(self) -> list[tuple[str, BaseLLM, str, str]]:
        nav_fallback_provider = (
            self._config_str(self._config.active_provider)
            or self._config_str(self._config.llm_provider)
        )
        nav_fallback_model = (
            self._config_str(self._config.active_model)
            or self._config_str(self._llm.model_name or "")
        )
        plan_fallback_provider = (
            self._config_str(getattr(self._config, "active_planning_provider", ""))
            or self._config_str(self._config.planner_llm_provider)
            or nav_fallback_provider
        )
        plan_fallback_model = (
            self._config_str(self._config.planner_model)
            or self._config_str(self._planner_llm.model_name or "")
            or nav_fallback_model
        )
        seen: dict[int, tuple[str, BaseLLM, str, str]] = {}
        for role, llm, provider, model in (
            ("navigation", self._llm, nav_fallback_provider, nav_fallback_model),
            ("planning", self._planner_llm, plan_fallback_provider, plan_fallback_model),
        ):
            billing_provider, billing_model = self._llm_billing_identity(
                llm,
                fallback_provider=provider,
                fallback_model=model,
            )
            seen[id(llm)] = (role, llm, billing_provider, billing_model)
        return list(seen.values())

    def _llm_usage_sources(self) -> list[tuple[BaseLLM, str, str]]:
        return [(llm, provider, model) for _, llm, provider, model in self._llm_usage_entries()]

    def _emit_tokens(self) -> None:
        total = self._context.message_manager.history.total_tokens
        prompt_tokens = 0
        completion_tokens = 0
        cache_tokens = 0
        cost_parts: list[float | None] = []
        cost_breakdown: list[dict[str, object]] = []
        for role, llm, provider, model in self._llm_usage_entries():
            usage = llm.get_accumulated_usage()
            llm_prompt = usage.get("prompt_tokens", 0)
            llm_completion = usage.get("completion_tokens", 0)
            llm_cache = usage.get("cache_tokens", 0)
            prompt_tokens += llm_prompt
            completion_tokens += llm_completion
            cache_tokens += llm_cache
            part_cost = compute_cost_usd(
                provider,
                model,
                prompt_tokens=llm_prompt,
                completion_tokens=llm_completion,
                cache_tokens=llm_cache,
            )
            cost_parts.append(part_cost)
            cost_breakdown.append(
                {
                    "role": role,
                    "provider": provider,
                    "model": model,
                    "prompt_tokens": llm_prompt,
                    "completion_tokens": llm_completion,
                    "cache_tokens": llm_cache,
                    "cost_usd": part_cost,
                }
            )
        if prompt_tokens == 0 and completion_tokens == 0:
            prompt_tokens = total
        tokens = prompt_tokens + completion_tokens
        if any(part is not None for part in cost_parts):
            cost_usd = sum(part or 0.0 for part in cost_parts)
        else:
            cost_usd = None
        payload: dict[str, object] = {
            "type": "tokens_update",
            "tokens": tokens or total,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_tokens": cache_tokens,
            "cost_usd": cost_usd,
        }
        if len(cost_breakdown) > 1:
            payload["cost_breakdown"] = cost_breakdown
        self._emit(payload)

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
        step = 0

        try:
            for step in range(context.options.max_steps):
                context.step_info = AgentStepInfo(
                    step_number=context.n_steps,
                    max_steps=context.options.max_steps,
                )

                if self._should_stop():
                    break

                self._hitl.process_pending_commands()

                should_plan = (
                    context.force_replan_after_hitl
                    or context.pending_hitl_handoff is not None
                    or context.n_steps % context.options.planning_interval == 0
                )
                if should_plan:
                    if context.pending_hitl_handoff:
                        self._run_hitl_debrief()
                    if context.force_replan_after_hitl:
                        context.force_replan_after_hitl = False
                    latest_plan = self._run_planner()
                    if context.hitl_interrupt:
                        self._hitl.process_pending_commands()
                        if self._should_stop():
                            break
                        continue
                    if self._is_non_web_task_complete(latest_plan):
                        return context.final_answer
                    if self._check_task_completion(latest_plan):
                        plan_result = latest_plan.get("result") if latest_plan else None
                        answer = ""
                        if plan_result:
                            answer = str(plan_result.get("final_answer") or "")
                        return self._finalize_with_criteria(answer or context.final_answer or "")
                    if self._should_skip_navigation(latest_plan):
                        continue

                self._hitl.process_pending_commands()
                if self._should_stop():
                    break

                nav_outcome = self._navigate()
                if nav_outcome == "complete":
                    return self._finalize_with_criteria(context.final_answer or "")
                if nav_outcome == "interrupted":
                    if self._should_stop():
                        break
                    continue
                if nav_outcome == "requested_done":
                    latest_plan = self._run_planner()
                    if self._check_task_completion(latest_plan):
                        plan_result = latest_plan.get("result") if latest_plan else None
                        answer = ""
                        if plan_result:
                            answer = str(plan_result.get("final_answer") or "")
                        return self._finalize_with_criteria(
                            answer or self._nav_done_answer() or context.final_answer or ""
                        )
                    self._reject_premature_done(latest_plan)
                    if (
                        context.consecutive_unvalidated_done
                        >= context.options.max_unvalidated_dones
                    ):
                        return self._finalize_with_criteria(
                            self._nav_done_answer() or context.final_answer or ""
                        )
                    continue
                if self._should_escalate_done_recovery():
                    return self._finalize_with_criteria(context.final_answer or "")

            if latest_plan and latest_plan.get("result", {}).get("done"):
                return self._finalize_with_criteria(context.final_answer or "")
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
            context.hitl_interrupt = False

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

    def _run_hitl_debrief(self) -> None:
        context = self._context
        handoff = context.pending_hitl_handoff
        if handoff is None:
            return

        console.print(
            Panel(
                "[dim]Analyzing human intervention…[/dim]",
                title="HITL debrief",
                border_style="yellow",
            )
        )
        self._log_section("HITL debrief")
        debrief_started = time.time()
        analysis = self._hitl_debrief.analyze(
            task=self._task,
            handoff=handoff,
            success_criteria=self._success_criteria,
        )
        debrief_ms = int((time.time() - debrief_started) * 1000)
        console.print(
            Panel(
                f"[dim]Debrief completed in {debrief_ms}ms[/dim]",
                title="HITL debrief",
                border_style="yellow",
            )
        )
        self._hitl.inject_human_memory(
            handoff.recorded,
            intervention_reason=handoff.intervention_reason,
            intervention_source=handoff.intervention_source,
            analysis=analysis if not analysis.get("error") else None,
        )

        self._emit(
            {
                "type": "human_handoff",
                "index": context.alloc_ui_step_index(),
                "cycle": handoff.cycle,
                "intervention_reason": handoff.intervention_reason,
                "intervention_source": handoff.intervention_source,
                "start_url": handoff.start_url,
                "start_title": handoff.start_title,
                "end_url": handoff.end_url,
                "end_title": handoff.end_title,
                "analysis": analysis,
                "actions": HitlDebriefAgent.serialize_actions(handoff),
            }
        )
        self._emit_tokens()
        context.pending_hitl_handoff = None

    def _finalize_with_criteria(self, final_answer: str) -> str:
        context = self._context
        self._log_section("Criteria checker")
        checker = CriteriaCheckerAgent(self._llm)
        checker._context = context
        state_message = CriteriaCheckerAgent.build_state_message(context)
        verdict = checker.check(
            task=self._task,
            success_criteria=context.success_criteria,
            state_message=state_message,
            final_answer=final_answer or context.final_answer or "",
        )
        preview = state_message.strip()
        if len(preview) > 4000:
            preview = preview[:4000] + "\n... [truncated]"
        if preview:
            verdict["observation_preview"] = preview

        context.criteria_verdict = verdict
        passed = bool(verdict.get("passed"))
        context.terminal_status = "pass" if passed else "fail"

        answer = (final_answer or "").strip()
        if not answer:
            answer = str(verdict.get("reason") or "").strip()
        if not answer:
            answer = str(verdict.get("evidence") or "").strip()
        if not answer:
            answer = "Success criteria met." if passed else "Success criteria not met."
        context.final_answer = answer

        context.consecutive_unvalidated_done = 0
        context.stuck_episode_active = False
        context.awaiting_done_recovery = False
        return context.final_answer

    def _nav_done_answer(self) -> str:
        result = self._last_nav_result or {}
        for action_result in reversed(result.get("action_results") or []):
            if getattr(action_result, "is_done", False):
                text = getattr(action_result, "extracted_content", None) or ""
                if text:
                    return str(text)
        return ""

    def _should_escalate_done_recovery(self) -> bool:
        if not self._context.awaiting_done_recovery:
            return False
        result = self._last_nav_result or {}
        if not result.get("done_blocked"):
            return False
        if result.get("only_wait_actions") or result.get("auto_wait"):
            return True
        action_results = result.get("action_results") or []
        return not action_results

    def _check_task_completion(self, plan_output: dict | None) -> bool:
        result = plan_output.get("result") if plan_output else None
        if result and result.get("done"):
            if result.get("final_answer"):
                self._context.final_answer = result["final_answer"]
            self._context.consecutive_unvalidated_done = 0
            self._context.stuck_episode_active = False
            self._context.awaiting_done_recovery = False
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
        self._context.awaiting_done_recovery = True
        plan_result = plan_output.get("result") if plan_output else None
        self._context.message_manager.add_message_with_tokens({
            "role": "user",
            "content": build_premature_done_rejection_hint(plan_result),
        })

    def _run_planner(self) -> dict | None:
        context = self._context
        try:
            context.check_cancelled()
            if context.hitl_interrupt:
                return None
            if context.post_hitl_fresh_start:
                context.message_manager.add_message_with_tokens(
                    {
                        "role": "user",
                        "content": (
                            "Human intervention completed. All prior plan next_steps are void. "
                            "Produce a new plan from the current page and human handoff only. "
                            "Treat the current page as authoritative — continue from where the human "
                            "left the browser. Do not navigate back to undo human path corrections. "
                            "Recompute remaining work from the task and current page evidence only."
                        ),
                    },
                    "hitl_replan",
                )
            position_for_plan = 0
            needs_current_state = (
                len(self._tasks) > 1
                or context.n_steps > 0
                or context.post_hitl_fresh_start
            )
            if needs_current_state:
                self._navigator.add_state_message_to_memory(
                    show_highlights=False,
                    wait_for_stable=False,
                )
                if context.hitl_interrupt:
                    self._navigator.remove_last_state_message_from_memory()
                    return None
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
            self._log_section(f"Planner (after step {context.n_steps})")
            plan_output = self._planner.execute()
            self._navigator.remove_last_state_message_from_memory()
            if context.hitl_interrupt:
                return None
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
        except HitlInterruptedError:
            return None
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
        self._log_section("Action critic")
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

        self._hitl.process_pending_commands()
        self._inject_stuck_recovery_hint(signals, result.get("diagnostics"))
        plan_output = self._run_planner()
        if self._check_task_completion(plan_output):
            return True

        if signals.needs_action_critic(self._context.critic_runs_this_episode):
            self._run_action_critic(signals)
        return False

    def _navigate(self) -> str | None:
        context = self._context
        self._last_nav_result = None
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
            self._log_section(f"Navigator step {context.n_steps + 1}")
            try:
                pre_state = context.browser_context.get_state(
                    show_highlights=False,
                    wait_for_stable=False,
                )
                log.info(
                    "%sNavigator step %d | url=%s title=%s | elements=%d",
                    self._run_prefix(),
                    context.n_steps + 1,
                    pre_state.url,
                    pre_state.title,
                    len(pre_state.selector_map),
                )
            except Exception:
                log.info(
                    "%sNavigator step %d | url=? title=? | elements=?",
                    self._run_prefix(),
                    context.n_steps + 1,
                )
            step_index = context.alloc_ui_step_index()
            self._emit({"type": "step_start", "step": build_step_start(step_index)})
            nav_started = time.time()
            nav_output = self._navigator.execute()
            if context.paused or context.stopped:
                return None

            if nav_output.get("interrupted"):
                self._hitl.process_pending_commands()
                interrupted = nav_output.get("result", {})
                self._emit(
                    {
                        "type": "step_end",
                        "index": step_index,
                        "nav_result": {
                            "interrupted": True,
                            "page_url": interrupted.get("page_url", ""),
                            "page_title": interrupted.get("page_title", ""),
                            "action_results": [],
                            "current_state": {
                                "evaluation_previous_goal": "Interrupted",
                                "memory": "Navigator interrupted for human control",
                                "next_goal": "",
                            },
                        },
                    }
                )
                return "interrupted"

            if nav_output.get("error"):
                raise RuntimeError(nav_output["error"])

            result = nav_output.get("result", {})
            context.n_steps += 1
            if context.post_hitl_fresh_start:
                context.post_hitl_fresh_start = False
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
                    log.info(
                        "%s│ step_timing dom_ms=%s llm_ms=%s batch_ms=%s settle_ms=%s "
                        "recovery_attempts=%s rejected=%s",
                        self._run_prefix(),
                        metrics.get("dom_ms"),
                        metrics.get("llm_ms"),
                        metrics.get("batch_ms"),
                        metrics.get("settle_ms"),
                        metrics.get("recovery_attempts"),
                        metrics.get("rejected_actions"),
                    )
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
            self._last_nav_result = result or None

            # Done confirmation owns planner confirm/reject; skip stuck recovery so we
            # do not double-plan or drop the reject / finalize path.
            if result and result.get("requested_done"):
                return "requested_done"

            if result and self._handle_stuck_recovery(result):
                if self._context.final_answer:
                    return "complete"
                return None

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
        self._hitl.process_pending_commands()
        if self._hitl.check_timeout():
            return True
        while self._context.paused:
            self._hitl.process_pending_commands()
            if self._hitl.check_timeout():
                return True
            self._pump_while_paused()
            if self._context.stopped:
                return True
        if self._context.consecutive_failures >= self._context.options.max_failures:
            return True
        return False

    def _pump_while_paused(self) -> None:
        try:
            page = self._context.browser_context.get_current_page()
            page.playwright_page.wait_for_timeout(200)
        except Exception:
            time.sleep(0.2)

    def cancel(self):
        self._hitl.flush_recorded_to_history()
        self._context.stop()

    def pause(self):
        self._context.pause()

    def resume(self):
        self._context.resume()

    def cleanup(self):
        self._context.browser_context.close()
