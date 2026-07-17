from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from ..actions.builder import NavigatorActionRegistry, parse_actions
from ..actions.schemas import Action
from ..agent.context import ActionResult, AgentContext
from ..agent.history import AgentStepRecord, BrowserStateHistory
from ..agent.messages.utils import coerce_navigator_response, fix_actions, preview_text
from ..agent.submit_hint import build_submit_completeness_hint
from ..agent.compound_integrity import build_post_commit_no_wait_hint
from ..agent.verification import count_verification_issues, format_verification_hints
from ..agent.stuck_recovery import should_block_navigator_done
from ..browser.history import find_history_element_in_tree, resolve_history_element_in_tree
from ..browser.dom import DOMElementNode
from ..reporting.replay_script import DOM_ACTIONS
from ..browser.views import BrowserState
from ..utils.prompts import build_browser_state_message, get_navigator_system_prompt
from .base import BaseAgent
from ..llm.base import BaseLLM
from .errors import (
    ChatModelAuthError,
    ChatModelBadRequestError,
    ChatModelForbiddenError,
    RequestCancelledError,
    ResponseParseError,
    classify_llm_error,
)
from .recovery import (
    build_empty_action_repair_message,
    build_invalid_index_message,
    build_parse_repair_message,
    collect_rejected_actions,
    filter_actions_by_selector_map,
    format_valid_indices,
)

MAX_CONSECUTIVE_NO_ACTION_STEPS = 3

if TYPE_CHECKING:
    from ..agent.messages.service import MessageManager


class NavigatorAgent(BaseAgent):
    def __init__(
        self,
        llm: BaseLLM,
        context: AgentContext,
        message_manager: MessageManager,
        action_registry: NavigatorActionRegistry,
    ):
        super().__init__(
            llm,
            get_navigator_system_prompt(context.options.max_actions_per_step),
            message_manager=message_manager,
            agent_id="navigator",
        )
        self._context = context
        self._action_registry = action_registry

    def add_state_message_to_memory(
        self,
        *,
        show_highlights: bool = True,
        wait_for_stable: bool = False,
    ):
        if self._context.state_message_added:
            self.remove_last_state_message_from_memory()

        message_manager = self._context.message_manager
        for i, result in enumerate(self._context.action_results):
            if result.include_in_memory:
                memory_line = result.format_memory_line()
                if memory_line:
                    message_manager.add_message_with_tokens(
                        {"role": "user", "content": f"Action result: {memory_line}"}
                    )
                if result.error:
                    error = result.error.split("\n")[-1]
                    message_manager.add_message_with_tokens(
                        {"role": "user", "content": f"Action error: {error}"}
                    )
                self._context.action_results[i] = ActionResult()

        browser_state = self._context.browser_context.get_state(
            show_highlights=show_highlights,
            wait_for_stable=wait_for_stable,
        )
        state_message = build_browser_state_message(self._context, browser_state)
        message_manager.add_state_message(state_message)
        self._context.state_message_added = True
        return browser_state

    def remove_last_state_message_from_memory(self):
        if not self._context.state_message_added:
            return
        self._context.message_manager.remove_last_state_message()
        self._context.state_message_added = False

    def execute(self) -> dict:
        output: dict = {"id": self.id}
        recovery_attempts = 0
        try:
            dom_start = time.perf_counter()
            browser_state = self.add_state_message_to_memory(
                show_highlights=True,
                wait_for_stable=True,
            )
            if (
                self._context.last_step_had_commit
                and self._context.last_commit_snapshot is not None
                and self._context.last_commit_snapshot.url == browser_state.url
                and self._context.last_commit_snapshot.title == browser_state.title
            ):
                self._context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": (
                        "Previous step submitted on this page but the screen did not advance. "
                        "Re-check verified field values and retry the commit — do not wait."
                    ),
                })
            dom_ms = (time.perf_counter() - dom_start) * 1000

            messages = self._get_messages()
            prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
            observation_chars = len(
                str(messages[-1].get("content", "")) if messages else ""
            )

            llm_start = time.perf_counter()
            response, raw_llm_response, recovery_attempts, rejected_actions = (
                self._invoke_navigator_with_recovery(messages, browser_state)
            )
            llm_ms = (time.perf_counter() - llm_start) * 1000

            self.remove_last_state_message_from_memory()

            response = coerce_navigator_response(response)
            fixed_actions = fix_actions(response)
            if fixed_actions:
                response["action"] = fixed_actions
            if rejected_actions:
                self._context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": (
                        "Rejected actions from your last response: "
                        f"{json.dumps(rejected_actions, ensure_ascii=False)}. "
                        "Use only allowed action names from the system prompt."
                    ),
                })
            current_state = response.get("current_state", {
                "evaluation_previous_goal": "Unknown",
                "memory": "",
                "next_goal": "",
            })
            raw_actions = response.get("action", [])
            if isinstance(raw_actions, dict):
                raw_actions = [raw_actions]

            actions = parse_actions(raw_actions, self._context.options.max_actions_per_step)
            num_elements = len(browser_state.selector_map)
            auto_wait = False
            escalate_recovery = False

            if not actions:
                self._context.consecutive_no_action_steps += 1
                if self._context.consecutive_no_action_steps >= MAX_CONSECUTIVE_NO_ACTION_STEPS:
                    escalate_recovery = True
                    self._context.consecutive_no_action_steps = MAX_CONSECUTIVE_NO_ACTION_STEPS - 1
                    self._context.message_manager.add_message_with_tokens({
                        "role": "user",
                        "content": (
                            "Navigator produced no parseable actions repeatedly. "
                            "Planner/critic recovery will run — respond with valid indexed actions next."
                        ),
                    })
                    actions = [
                        Action(
                            name="wait",
                            args={
                                "seconds": 3,
                                "intent": "Escalating recovery after repeated no-action responses",
                            },
                        )
                    ]
                    auto_wait = True
                else:
                    intent = (
                        "Auto-wait: page still loading (no interactive elements)"
                        if num_elements == 0
                        else "Auto-wait: model returned no parseable actions"
                    )
                    actions = [
                        Action(
                            name="wait",
                            args={"seconds": 3, "intent": intent},
                        )
                    ]
                    auto_wait = True
                    if num_elements > 0 and self._context.consecutive_no_action_steps == 1:
                        valid_indices = format_valid_indices(browser_state.selector_map)
                        self._context.message_manager.add_message_with_tokens({
                            "role": "user",
                            "content": build_empty_action_repair_message(valid_indices),
                        })
            else:
                self._context.consecutive_no_action_steps = 0

            invalid_index_actions: list[dict] = []
            if actions:
                actions, invalid_index_actions = filter_actions_by_selector_map(
                    actions,
                    browser_state.selector_map,
                )
                if invalid_index_actions:
                    valid_indices = format_valid_indices(browser_state.selector_map)
                    self._context.message_manager.add_message_with_tokens({
                        "role": "user",
                        "content": build_invalid_index_message(
                            invalid_index_actions,
                            valid_indices,
                        ),
                    })
                if not actions and not auto_wait:
                    actions = [
                        Action(
                            name="wait",
                            args={"seconds": 2, "intent": "Re-evaluate after invalid indexes"},
                        )
                    ]
                    auto_wait = True

            post_commit_hint = build_post_commit_no_wait_hint(
                self._context,
                browser_state,
                actions,
            )
            if post_commit_hint:
                self._context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": post_commit_hint,
                })

            done_blocked = False
            requested_done = any(action.name == "done" for action in actions)
            if requested_done and should_block_navigator_done(self._context):
                done_blocked = True
                actions = [action for action in actions if action.name != "done"]
                requested_done = False
                self._context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": (
                        "done was blocked: the task is not verified complete on the current page. "
                        "Inspect the indexed elements and continue with click_element / input_text / wait."
                    ),
                })
                if not actions:
                    actions = [Action(name="wait", args={"seconds": 2, "intent": "Re-evaluate page"})]

            model_output = {"current_state": current_state, "action": self._actions_to_dicts(actions)}
            self._context.message_manager.add_model_output(model_output)

            batch_start = time.perf_counter()
            action_results = self._action_registry.execute_multi(
                actions,
                self._context,
                browser_state=browser_state,
            )
            batch_ms = (time.perf_counter() - batch_start) * 1000
            self._context.action_results = action_results

            settle_start = time.perf_counter()
            after_state = self._context.browser_context.get_state(
                show_highlights=False,
                wait_for_stable=True,
            )
            settle_ms = (time.perf_counter() - settle_start) * 1000
            self._context.browser_context.remove_highlight()
            submit_hint = build_submit_completeness_hint(actions, browser_state, after_state)
            verification_hint = format_verification_hints(action_results)
            submit_hint_fired = False
            if verification_hint:
                self._context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": verification_hint,
                })
            elif submit_hint:
                submit_hint_fired = True
                self._context.message_manager.add_message_with_tokens({
                    "role": "user",
                    "content": submit_hint,
                })

            verification_counts = count_verification_issues(action_results)
            self._context.last_step_metrics = {
                "dom_ms": round(dom_ms, 1),
                "llm_ms": round(llm_ms, 1),
                "batch_ms": round(batch_ms, 1),
                "settle_ms": round(settle_ms, 1),
                "prompt_chars": prompt_chars,
                "observation_chars": observation_chars,
                "num_highlights": num_elements,
                "recovery_attempts": recovery_attempts,
                "rejected_actions": len(rejected_actions) + len(invalid_index_actions),
                "verified_actions": verification_counts.get("verified", 0),
                "no_effect_actions": verification_counts.get("no_effect", 0),
                "failed_verifications": verification_counts.get("failed", 0),
            }

            executed_done = bool(action_results) and action_results[-1].is_done
            only_wait_actions = bool(actions) and all(action.name == "wait" for action in actions)
            only_done_action = bool(actions) and all(action.name == "done" for action in actions)
            output["result"] = {
                "requested_done": executed_done,
                "done": False,
                "done_blocked": done_blocked,
                "current_state": current_state,
                "actions": actions,
                "auto_wait": auto_wait,
                "consecutive_no_action_steps": self._context.consecutive_no_action_steps,
                "submit_hint_fired": submit_hint_fired,
                "verification_issues": verification_counts.get("no_effect", 0)
                + verification_counts.get("failed", 0),
                "action_results": action_results,
                "page_url": after_state.url,
                "page_title": after_state.title,
                "only_wait_actions": only_wait_actions,
                "only_done_action": only_done_action,
                "escalate_recovery": escalate_recovery,
            }
            if auto_wait:
                output["result"]["diagnostics"] = self._build_no_action_diagnostics(
                    response,
                    raw_llm_response,
                    num_elements,
                )

            self._record_step_history(
                model_output=json.dumps(model_output),
                action_results=action_results,
                browser_state=browser_state,
                actions=actions,
            )
            self._record_progress(
                browser_state=browser_state,
                current_state=current_state,
                actions=actions,
                action_results=action_results,
            )
            return output
        except Exception as error:
            self.remove_last_state_message_from_memory()
            classified = classify_llm_error(error)
            if isinstance(
                classified,
                (
                    ChatModelAuthError,
                    ChatModelBadRequestError,
                    ChatModelForbiddenError,
                    RequestCancelledError,
                ),
            ):
                raise classified from error
            output["error"] = str(error)
            return output

    def _invoke_navigator_with_recovery(
        self,
        messages: list[dict],
        browser_state: BrowserState,
    ) -> tuple[dict, str, int, list]:
        valid_indices = format_valid_indices(browser_state.selector_map)
        recovery_attempts = 0
        rejected_actions: list = []

        try:
            response, raw = self.get_json_response_with_raw(messages, temperature=0.1)
        except ResponseParseError as error:
            recovery_attempts = 1
            repair_messages = [
                *messages,
                {
                    "role": "user",
                    "content": build_parse_repair_message(
                        error=str(error),
                        valid_indices=valid_indices,
                    ),
                },
            ]
            response, raw = self.get_json_response_with_raw(repair_messages, temperature=0.1)

        raw_before_validation = fix_actions(response)
        rejected_actions = collect_rejected_actions(
            raw_before_validation,
            response.get("action", []),
        )
        if not response.get("action") and raw_before_validation:
            recovery_attempts += 1
            repair_messages = [
                *messages,
                {
                    "role": "user",
                    "content": build_parse_repair_message(
                        error="all actions were rejected during validation",
                        valid_indices=valid_indices,
                        rejected_actions=rejected_actions,
                    ),
                },
            ]
            response, raw = self.get_json_response_with_raw(repair_messages, temperature=0.1)
            raw_before_validation = fix_actions(response)
            rejected_actions = collect_rejected_actions(
                raw_before_validation,
                response.get("action", []),
            )

        return response, raw, recovery_attempts, rejected_actions

    def _record_progress(
        self,
        *,
        browser_state: BrowserState,
        current_state: dict,
        actions: list[Action],
        action_results: list[ActionResult],
    ) -> None:
        action_summary = ", ".join(
            f"{action.name}({json.dumps(action.args, ensure_ascii=False)})"
            for action in actions[:3]
        )
        error = ""
        for result in action_results:
            if result.error:
                error = result.error.split("\n")[-1]
                break
        step_number = self._context.n_steps + 1
        self._context.message_manager.record_progress_step(
            step_number=step_number,
            url=browser_state.url,
            title=browser_state.title,
            evaluation=str(current_state.get("evaluation_previous_goal", "")),
            memory=str(current_state.get("memory", "")),
            next_goal=str(current_state.get("next_goal", "")),
            action_summary=action_summary,
            error=error,
        )

    @staticmethod
    def _actions_to_dicts(actions: list[Action]) -> list[dict]:
        return [{action.name: action.args} for action in actions]

    @staticmethod
    def _build_no_action_diagnostics(
        response: dict,
        raw_llm_response: str,
        num_elements: int,
    ) -> dict:
        return {
            "parsed_keys": sorted(response.keys()),
            "raw_action": response.get("action", response.get("actions")),
            "num_elements": num_elements,
            "raw_preview": preview_text(raw_llm_response),
        }

    def _record_step_history(
        self,
        *,
        model_output: str,
        action_results: list[ActionResult],
        browser_state: BrowserState,
        actions: list[Action],
    ) -> None:
        interacted_elements = []
        for action, result in zip(actions, action_results):
            if result.interacted_element is not None:
                interacted_elements.append(result.interacted_element)
            elif self._action_registry.has_index(action.name) and action.index is not None:
                element = browser_state.selector_map.get(action.index)
                if element is not None:
                    from ..browser.history import convert_dom_element_to_history_element

                    interacted_elements.append(convert_dom_element_to_history_element(element))
                else:
                    interacted_elements.append(None)
            else:
                interacted_elements.append(None)

        state_history = BrowserStateHistory(
            url=browser_state.url,
            title=browser_state.title,
            tabs=browser_state.tabs,
            interacted_elements=interacted_elements,
        )
        self._context.history.history.append(
            AgentStepRecord(
                model_output=model_output,
                result=list(action_results),
                state=state_history,
            )
        )

    def parse_history_model_output(self, history_item: AgentStepRecord) -> dict[str, Any]:
        if not history_item.model_output:
            raise ValueError("Missing model output in history item")
        parsed = json.loads(history_item.model_output)
        actions = fix_actions(parsed)
        goal = ""
        current_state = parsed.get("current_state", {})
        if isinstance(current_state, dict):
            goal = current_state.get("next_goal", "")
        return {
            "parsed_output": parsed,
            "goal": goal,
            "actions_to_replay": actions,
        }

    def update_action_indices(
        self,
        historical_element,
        action_dict: dict[str, Any],
        current_state: BrowserState,
    ) -> dict[str, Any] | None:
        if historical_element is None:
            return action_dict
        current_element = find_history_element_in_tree(
            historical_element,
            current_state.element_tree,
        )
        if current_element is None or current_element.highlight_index is None:
            return None
        if len(action_dict) != 1:
            return action_dict
        action_name, action_args = next(iter(action_dict.items()))
        if not isinstance(action_args, dict):
            return action_dict
        if "index" not in action_args:
            return action_dict
        old_index = action_args.get("index")
        if old_index != current_element.highlight_index:
            updated_args = dict(action_args)
            updated_args["index"] = current_element.highlight_index
            return {action_name: updated_args}
        return action_dict

    @staticmethod
    def _is_indexed_dom_action(raw_action: dict[str, Any]) -> bool:
        if len(raw_action) != 1:
            return False
        action_name, action_args = next(iter(raw_action.items()))
        return (
            action_name in DOM_ACTIONS
            and isinstance(action_args, dict)
            and "index" in action_args
        )

    def _replay_show_highlights(self) -> bool:
        return self._context.options.replay_show_highlights

    def _remap_single_history_action(
        self,
        historical_element,
        raw_action: dict[str, Any],
        browser_state: BrowserState,
    ) -> tuple[dict[str, Any] | None, dict[int, DOMElementNode], BrowserState]:
        overrides: dict[int, DOMElementNode] = {}

        updated = self.update_action_indices(historical_element, raw_action, browser_state)
        if updated is not None:
            return updated, overrides, browser_state

        if not self._is_indexed_dom_action(raw_action):
            return None, overrides, browser_state

        action_name, action_args = next(iter(raw_action.items()))
        original_index = action_args.get("index")

        browser_state = self._context.browser_context.get_state(
            show_highlights=self._replay_show_highlights(),
            wait_for_stable=True,
        )
        updated = self.update_action_indices(historical_element, raw_action, browser_state)
        if updated is not None:
            return updated, overrides, browser_state

        if historical_element is None:
            return None, overrides, browser_state

        resolved = resolve_history_element_in_tree(
            historical_element,
            browser_state.element_tree,
        )

        if resolved is None:
            return None, overrides, browser_state

        map_index = resolved.highlight_index if resolved.highlight_index is not None else original_index
        if map_index is None:
            return None, overrides, browser_state

        map_index = int(map_index)
        overrides[map_index] = resolved
        final_args = dict(action_args)
        final_args["index"] = map_index
        return {action_name: final_args}, overrides, browser_state

    def _collect_remapped_actions(
        self,
        history_item: AgentStepRecord,
        actions_to_replay: list[Any],
        browser_state: BrowserState,
        *,
        only_indices: set[int] | None = None,
    ) -> tuple[list[Action], dict[int, DOMElementNode], BrowserState, list[str], set[int]]:
        remapped_actions: list[Action] = []
        selector_overrides: dict[int, DOMElementNode] = {}
        failed_actions: list[str] = []
        failed_indices: set[int] = set()

        for index, raw_action in enumerate(actions_to_replay):
            if raw_action is None:
                continue
            if only_indices is not None and index not in only_indices:
                continue

            historical_element = None
            if index < len(history_item.state.interacted_elements):
                historical_element = history_item.state.interacted_elements[index]
            updated, overrides, browser_state = self._remap_single_history_action(
                historical_element,
                raw_action,
                browser_state,
            )
            if updated is None:
                if self._is_indexed_dom_action(raw_action):
                    failed_actions.append(next(iter(raw_action.keys())))
                    failed_indices.add(index)
                continue
            selector_overrides.update(overrides)
            remapped_actions.extend(parse_actions([updated], self._context.options.max_actions_per_step))

        return remapped_actions, selector_overrides, browser_state, failed_actions, failed_indices

    def execute_history_actions(
        self,
        history_item: AgentStepRecord,
        actions_to_replay: list[Any],
        delay_seconds: float,
    ) -> list[ActionResult]:
        browser_state = self._context.browser_context.get_state(
            show_highlights=self._replay_show_highlights(),
            wait_for_stable=True,
        )
        remapped_actions, selector_overrides, browser_state, failed_actions, failed_indices = (
            self._collect_remapped_actions(
                history_item,
                actions_to_replay,
                browser_state,
            )
        )

        retry_wait = self._context.options.replay_action_retry_wait_seconds
        if (
            not remapped_actions
            and failed_indices
            and retry_wait > 0
            and not self._context.stopped
            and not self._context.paused
        ):
            time.sleep(retry_wait)
            if not self._context.stopped and not self._context.paused:
                browser_state = self._context.browser_context.get_state(
                    show_highlights=False,
                    wait_for_stable=True,
                )
                retry_actions, retry_overrides, browser_state, retry_failed, _retry_indices = (
                    self._collect_remapped_actions(
                        history_item,
                        actions_to_replay,
                        browser_state,
                        only_indices=failed_indices,
                    )
                )
                remapped_actions.extend(retry_actions)
                selector_overrides.update(retry_overrides)
                failed_actions = retry_failed

        if not remapped_actions:
            page_url = history_item.state.url or "unknown"
            failed_label = ", ".join(failed_actions) if failed_actions else "all actions"
            return [
                ActionResult(
                    error=(
                        f"No replayable actions at {page_url} after remapping ({failed_label})"
                    )
                )
            ]

        return self._action_registry.execute_multi(
            remapped_actions,
            self._context,
            browser_state=browser_state,
            selector_overrides=selector_overrides or None,
            action_retry_wait_seconds=self._context.options.replay_action_retry_wait_seconds,
        )

    def execute_history_step(
        self,
        history_item: AgentStepRecord,
        step_index: int,
        total_steps: int,
        max_retries: int = 3,
        delay_seconds: float = 1.0,
        skip_failures: bool = True,
    ) -> list[ActionResult]:
        try:
            parsed_data = self.parse_history_model_output(history_item)
        except Exception as error:
            return [ActionResult(error=f"Step {step_index + 1}: {error}")]

        actions_to_replay = parsed_data["actions_to_replay"]
        for attempt in range(max_retries):
            if self._context.stopped:
                break
            try:
                return self.execute_history_actions(history_item, actions_to_replay, delay_seconds)
            except Exception as error:
                if attempt + 1 >= max_retries:
                    message = f"Step {step_index + 1} failed after {max_retries} attempts: {error}"
                    if skip_failures:
                        return [ActionResult(error=message, include_in_memory=True)]
                    raise RuntimeError(message) from error
                time.sleep(delay_seconds)
        return []

    def reset(self):
        super().reset()
