from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from ..agent.context import ActionResult, AgentContext
from ..agent.messages.utils import wrap_untrusted_content
from ..agent.compound_integrity import (
    BatchState,
    MutationRecord,
    format_related_control_states,
    is_commit_action,
    is_mutation_action,
    record_commit_outcome,
    reverify_mutations,
)
from ..agent.verification import (
    VERIFICATION_FAILED,
    VERIFICATION_NO_EFFECT,
    VERIFICATION_VERIFIED,
    PageSnapshot,
    apply_verification,
    capture_page_snapshot,
    probe_element,
    redact_input_message,
)
from ..browser.dom import DOMElementNode
from ..browser.history import (
    DOMHistoryElement,
    convert_dom_element_to_history_element,
    is_file_uploader,
    resolve_history_element_in_tree,
)
from ..browser.views import BrowserState, ScrollRegion, URLNotAllowedError
from .schemas import Action


def _history_element_from_scroll_region(region: ScrollRegion | None) -> DOMHistoryElement | None:
    """Capture container scroll targets for replay; window scrolls stay locatoreless."""
    if region is None or region.kind != "container":
        return None
    xpath = (region.xpath or "").strip()
    if not xpath:
        return None
    return DOMHistoryElement(
        tag_name=region.tag or "div",
        xpath=xpath,
        highlight_index=None,
    )


def _resolve_element_for_action(
    action: Action,
    selector_map: dict[int, DOMElementNode],
    *,
    element_tree: DOMElementNode | None = None,
    original_element: DOMElementNode | None = None,
) -> DOMElementNode | None:
    """Resolve an action target, preferring stable identity over rebuilt highlight indexes."""
    if action.index is None:
        return None
    if original_element is not None:
        if isinstance(element_tree, DOMElementNode):
            history = convert_dom_element_to_history_element(original_element)
            remapped = resolve_history_element_in_tree(history, element_tree)
            if remapped is not None:
                return remapped
        for candidate in selector_map.values():
            if (
                isinstance(candidate, DOMElementNode)
                and candidate.xpath
                and candidate.xpath == original_element.xpath
            ):
                return candidate
        return None
    candidate = selector_map.get(action.index)
    return candidate if isinstance(candidate, DOMElementNode) else None


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}".lower()


_NAVIGATION_ACTIONS = frozenset({
    "go_to_url",
    "go_back",
    "search_google",
    "open_tab",
})

_PAGE_STATE_CHANGING_ACTIONS = _NAVIGATION_ACTIONS | frozenset({
    "click_element",
    "send_keys",
})

_INTERACTION_ACTIONS = frozenset({
    "click_element",
    "input_text",
    "send_keys",
    "select_dropdown_option",
})


def _needs_inter_action_stable_wait(action: Action, *, is_last_in_batch: bool) -> bool:
    """One stable wait between batch actions; the final settle is handled by the navigator."""
    if is_last_in_batch:
        return False
    if action.name in _NAVIGATION_ACTIONS:
        return False
    if action.name == "wait":
        return False
    return action.name in _INTERACTION_ACTIONS


def _wait_before_verification_snapshot(page, action: Action, *, is_last_in_batch: bool) -> None:
    """Flush deferred interaction settle before page reads used for verification."""
    if (
        _needs_inter_action_stable_wait(action, is_last_in_batch=is_last_in_batch)
        or page.defer_post_action_stable
    ):
        page.wait_for_page_stable(minimum_wait=0.1)


def _action_will_navigate(action: Action, page_url: str) -> bool:
    if action.name in ("go_back", "search_google", "open_tab"):
        return True
    if action.name == "go_to_url":
        url = action.args.get("url", "")
        return _normalize_url(url) != _normalize_url(page_url)
    return False


def _action_breaks_sequence(before_url: str, after_url: str, before_title: str, after_title: str) -> bool:
    return before_url != after_url or before_title != after_title


@dataclass
class _ActionAttempt:
    result: ActionResult
    locate_element: DOMElementNode | None
    before_snapshot: PageSnapshot
    after_snapshot: PageSnapshot
    pending_commit: bool
    blocked: ActionResult | None = None
    browser_state: BrowserState | None = None
    page_url: str | None = None
    page_title: str | None = None


class NavigatorActionRegistry:
    def __init__(self, actions: dict[str, Callable[[dict[str, Any]], ActionResult]]):
        self._actions = actions
        self._has_index: dict[str, bool] = {
            "click_element": True,
            "input_text": True,
            "get_dropdown_options": True,
            "select_dropdown_option": True,
            "scroll_to_percent": True,
            "scroll_to_top": True,
            "scroll_to_bottom": True,
            "previous_page": True,
            "next_page": True,
        }

    def get_action_names(self) -> list[str]:
        return list(self._actions.keys())

    def has_index(self, name: str) -> bool:
        return self._has_index.get(name, False)

    def execute(self, action: Action, selector_map: dict[int, DOMElementNode]) -> ActionResult:
        handler = self._actions.get(action.name)
        if handler is None:
            return ActionResult(error=f"Unknown action: {action.name}")
        try:
            return handler(action.args, selector_map)
        except Exception as e:
            return ActionResult(error=str(e))

    def _run_action_attempt(
        self,
        *,
        action: Action,
        action_index: int,
        total_actions: int,
        context: AgentContext,
        page,
        browser_context,
        selector_map: dict[int, DOMElementNode],
        browser_state: BrowserState,
        original_elements: dict[int, DOMElementNode],
        batch: BatchState,
    ) -> _ActionAttempt:
        page_url = browser_state.url
        page_title = browser_state.title
        updated_state = browser_state

        if action.index is not None and action.index not in selector_map:
            fresh_state = browser_context.get_state(show_highlights=False, wait_for_stable=False)
            selector_map.clear()
            selector_map.update(fresh_state.selector_map)
            updated_state = fresh_state
            page_url = fresh_state.url
            page_title = fresh_state.title

        original = (
            original_elements.get(action.index)
            if action.index is not None
            else None
        )
        element = _resolve_element_for_action(
            action,
            selector_map,
            element_tree=getattr(updated_state, "element_tree", None),
            original_element=original,
        )
        locate_element = element
        tab_ids = browser_context.get_all_tab_ids()
        before_snapshot = capture_page_snapshot(page, tab_ids)
        before_element = probe_element(
            page,
            locate_element,
            expected_value=str(action.args.get("text", "")) if action.name == "input_text" else None,
            expected_selected_text=str(action.args.get("text", ""))
            if action.name == "select_dropdown_option"
            else None,
        )

        if action.name in _NAVIGATION_ACTIONS:
            browser_context.remove_highlight()

        pending_commit = is_commit_action(action, locate_element)
        if pending_commit and batch.mutations:
            ok, issues = reverify_mutations(page, batch)
            if not ok:
                blocked = ActionResult(
                    extracted_content=(
                        "Commit blocked: prior mutations no longer verified — "
                        + "; ".join(issues)
                    ),
                    error="Commit blocked due to mutation regression",
                    include_in_memory=True,
                    action_name=action.name,
                    action_index=action.index,
                    verification_status=VERIFICATION_FAILED,
                    verification_evidence="; ".join(issues)[:160],
                )
                return _ActionAttempt(
                    result=blocked,
                    locate_element=locate_element,
                    before_snapshot=before_snapshot,
                    after_snapshot=before_snapshot,
                    pending_commit=pending_commit,
                    blocked=blocked,
                    browser_state=updated_state,
                    page_url=page_url,
                    page_title=page_title,
                )

        exec_map = dict(selector_map)
        if locate_element is not None and action.index is not None:
            exec_map[action.index] = locate_element
        result = self.execute(action, exec_map)
        if locate_element is not None and action.index is not None:
            result.interacted_element = convert_dom_element_to_history_element(locate_element)

        is_last_in_batch = action_index == total_actions - 1
        _wait_before_verification_snapshot(
            page,
            action,
            is_last_in_batch=is_last_in_batch,
        )
        after_snapshot = capture_page_snapshot(page, browser_context.get_all_tab_ids())
        after_element = probe_element(
            page,
            locate_element,
            expected_value=str(action.args.get("text", "")) if action.name == "input_text" else None,
            expected_selected_text=str(action.args.get("text", ""))
            if action.name == "select_dropdown_option"
            else None,
        )
        apply_verification(
            action,
            result,
            before=before_snapshot,
            after=after_snapshot,
            before_element=before_element,
            after_element=after_element,
            element=locate_element,
        )

        return _ActionAttempt(
            result=result,
            locate_element=locate_element,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_commit=pending_commit,
            browser_state=updated_state,
            page_url=page_url,
            page_title=page_title,
        )

    def execute_multi(
        self,
        actions: list[Action],
        context: AgentContext,
        browser_state: BrowserState | None = None,
        selector_overrides: dict[int, DOMElementNode] | None = None,
        action_retry_wait_seconds: float | None = None,
    ) -> list[ActionResult]:
        results: list[ActionResult] = []
        browser_context = context.browser_context
        page = browser_context.get_current_page()

        if browser_state is None:
            browser_state = browser_context.get_state(show_highlights=True)

        if not actions:
            return results

        selector_map = dict(browser_state.selector_map)
        if selector_overrides:
            selector_map.update(selector_overrides)
        original_elements: dict[int, DOMElementNode] = {
            index: node for index, node in selector_map.items()
        }
        page_url = browser_state.url
        page_title = browser_state.title
        action_delay = context.options.action_delay_seconds
        err_count = 0
        batch = BatchState()
        step_start_snapshot = capture_page_snapshot(page, browser_context.get_all_tab_ids())
        had_commit = False
        page_advanced = False
        page.set_defer_post_action_stable(True)

        try:
            for i, action in enumerate(actions):
                if context.hitl_interrupt or context.paused or context.stopped:
                    break

                attempt = self._run_action_attempt(
                    action=action,
                    action_index=i,
                    total_actions=len(actions),
                    context=context,
                    page=page,
                    browser_context=browser_context,
                    selector_map=selector_map,
                    browser_state=browser_state,
                    original_elements=original_elements,
                    batch=batch,
                )
                if attempt.browser_state is not None:
                    browser_state = attempt.browser_state
                if attempt.page_url is not None:
                    page_url = attempt.page_url
                if attempt.page_title is not None:
                    page_title = attempt.page_title

                if attempt.blocked is not None:
                    results.append(attempt.blocked)
                    break

                result = attempt.result
                locate_element = attempt.locate_element
                before_snapshot = attempt.before_snapshot
                after_snapshot = attempt.after_snapshot
                pending_commit = attempt.pending_commit

                if (
                    action_retry_wait_seconds
                    and result.error
                    and not context.stopped
                    and not context.paused
                ):
                    time.sleep(action_retry_wait_seconds)
                    if not context.stopped and not context.paused:
                        fresh_state = browser_context.get_state(
                            show_highlights=False,
                            wait_for_stable=True,
                        )
                        selector_map = dict(fresh_state.selector_map)
                        if selector_overrides:
                            selector_map.update(selector_overrides)
                        browser_state = fresh_state
                        page_url = fresh_state.url
                        page_title = fresh_state.title

                        retry = self._run_action_attempt(
                            action=action,
                            action_index=i,
                            total_actions=len(actions),
                            context=context,
                            page=page,
                            browser_context=browser_context,
                            selector_map=selector_map,
                            browser_state=browser_state,
                            original_elements=original_elements,
                            batch=batch,
                        )
                        if retry.browser_state is not None:
                            browser_state = retry.browser_state
                        if retry.page_url is not None:
                            page_url = retry.page_url
                        if retry.page_title is not None:
                            page_title = retry.page_title
                        if retry.blocked is not None:
                            results.append(retry.blocked)
                            break
                        result = retry.result
                        locate_element = retry.locate_element
                        before_snapshot = retry.before_snapshot
                        after_snapshot = retry.after_snapshot
                        pending_commit = retry.pending_commit

                if (
                    is_mutation_action(action)
                    and locate_element is not None
                    and result.verification_status == VERIFICATION_VERIFIED
                ):
                    batch.mutations.append(
                        MutationRecord(
                            action=action,
                            element=locate_element,
                            expected_value=str(action.args.get("text", ""))
                            if action.name == "input_text"
                            else None,
                            expected_selected_text=str(action.args.get("text", ""))
                            if action.name == "select_dropdown_option"
                            else None,
                        )
                    )
                    if action.index is not None:
                        batch.mutation_indices.add(action.index)

                if is_mutation_action(action) and result.extracted_content:
                    related = format_related_control_states(page, selector_map)
                    if related:
                        result.extracted_content = f"{result.extracted_content}\n{related}"

                if pending_commit:
                    had_commit = True
                    page_advanced = before_snapshot.page_changed(after_snapshot)

                results.append(result)

                if result.error:
                    context.record_failed_action(
                        page_url,
                        action.name,
                        dict(action.args),
                        result.error,
                    )

                if result.is_done:
                    break
                if result.error or result.verification_status == VERIFICATION_FAILED:
                    err_count += 1
                    if err_count >= 3:
                        break
                    break

                # Refresh page metadata for sequence control, but keep using observation-time
                # element identities for subsequent indexed actions on the same page.
                post_state = browser_context.get_state(show_highlights=False, wait_for_stable=False)
                selector_map = post_state.selector_map
                browser_state = post_state
                page_url = post_state.url
                page_title = post_state.title

                if i < len(actions) - 1:
                    next_action = actions[i + 1]
                    if _action_breaks_sequence(
                        before_snapshot.url,
                        after_snapshot.url,
                        before_snapshot.title,
                        after_snapshot.title,
                    ):
                        results.append(
                            ActionResult(
                                extracted_content=(
                                    f"Action sequence stopped after action {i + 1}/{len(actions)} due to navigation"
                                ),
                                include_in_memory=True,
                            )
                        )
                        break

                    if next_action.index is not None and self.has_index(next_action.name):
                        next_original = original_elements.get(next_action.index)
                        next_element = _resolve_element_for_action(
                            next_action,
                            selector_map,
                            element_tree=post_state.element_tree,
                            original_element=next_original,
                        )
                        if next_element is None and next_original is None:
                            results.append(
                                ActionResult(
                                    extracted_content=(
                                        f"Action sequence stopped: index {next_action.index} "
                                        f"not found after action {i + 1}/{len(actions)}"
                                    ),
                                    include_in_memory=True,
                                )
                            )
                            break

                    time.sleep(action_delay)

            record_commit_outcome(
                context,
                snapshot=step_start_snapshot,
                had_commit=had_commit,
                page_advanced=page_advanced,
            )
        finally:
            page.set_defer_post_action_stable(False)

        return results


def parse_actions(raw_actions: list[Any], max_actions: int) -> list[Action]:
    actions: list[Action] = []
    for raw in raw_actions[:max_actions]:
        if raw is None:
            continue
        if isinstance(raw, dict):
            if "type" in raw:
                action_type = raw.pop("type")
                args = dict(raw)
                actions.append(Action(name=action_type, args=args))
                continue
            if len(raw) == 1:
                name, args = next(iter(raw.items()))
                if isinstance(args, dict):
                    actions.append(Action(name=name, args=args))
                else:
                    actions.append(Action(name=name, args={}))
                continue
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                actions.extend(parse_actions([parsed], max_actions - len(actions)))
            except json.JSONDecodeError:
                continue
    return actions


class ActionBuilder:
    def __init__(self, context: AgentContext):
        self._context = context

    def build_default_actions(self) -> NavigatorActionRegistry:
        ctx = self._context

        def get_page():
            return ctx.browser_context.get_current_page()

        def get_element(index: int | None, selector_map: dict[int, DOMElementNode]) -> DOMElementNode:
            if index is None or index not in selector_map:
                raise ValueError(f"Element with index {index} not found")
            return selector_map[index]

        def optional_element(index: int | None, selector_map: dict[int, DOMElementNode]) -> DOMElementNode | None:
            if index is None:
                return None
            return selector_map.get(index)

        def optional_scroll_element(args: dict[str, Any], selector_map: dict[int, DOMElementNode]) -> DOMElementNode | None:
            raw = args.get("index")
            if raw is None or raw == "":
                return None
            try:
                index = int(raw)
            except (TypeError, ValueError):
                return None
            return selector_map.get(index)

        def _scroll_result_label(region) -> str:
            if region is None:
                return "No scrollable region found"
            if region.kind == "window":
                return "page"
            return f"container ({region.tag})"

        handlers: dict[str, Callable[[dict[str, Any], dict[int, DOMElementNode]], ActionResult]] = {}

        def done(args, _selector_map):
            text = args.get("text", "")
            success = args.get("success", True)
            return ActionResult(is_done=True, success=success, extracted_content=text)

        def search_google(args, _selector_map):
            query = args.get("query", args.get("text", ""))
            ctx.browser_context.navigate_to(f"https://www.google.com/search?q={query}")
            msg = f"Searched Google for: {query}"
            return ActionResult(extracted_content=msg, include_in_memory=True)

        def go_to_url(args, _selector_map):
            url = args["url"]
            current_url = get_page().url()
            if _normalize_url(url) == _normalize_url(current_url):
                return ActionResult(
                    extracted_content=f"Already on {current_url}; skipped reload",
                    include_in_memory=True,
                )
            ctx.browser_context.navigate_to(url)
            msg = f"Navigated to {url}"
            return ActionResult(extracted_content=msg, include_in_memory=True)

        def go_back(_args, _selector_map):
            get_page().go_back()
            return ActionResult(extracted_content="Navigated back", include_in_memory=True)

        def wait_action(args, _selector_map):
            seconds = int(args.get("seconds", args.get("duration", 3)))
            deadline = time.time() + seconds
            while time.time() < deadline:
                if ctx.hitl_interrupt or ctx.paused or ctx.stopped:
                    break
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                time.sleep(min(0.2, remaining))
            waited = max(0, int(round(seconds - max(0.0, deadline - time.time()))))
            return ActionResult(
                extracted_content=f"Waited {waited} seconds",
                include_in_memory=True,
            )

        def click_element(args, selector_map):
            element = get_element(args.get("index"), selector_map)
            if is_file_uploader(element):
                return ActionResult(
                    extracted_content=(
                        f"Element {args.get('index')} is a file uploader and cannot be clicked directly"
                    ),
                    include_in_memory=True,
                )
            initial_tabs = ctx.browser_context.get_all_tab_ids()
            try:
                get_page().click_element(element)
            except URLNotAllowedError:
                raise
            except Exception as error:
                return ActionResult(error=str(error), include_in_memory=True)
            msg = f"Clicked element {args.get('index')}"
            current_tabs = ctx.browser_context.get_all_tab_ids()
            if len(current_tabs) > len(initial_tabs):
                new_tab = (current_tabs - initial_tabs).pop()
                ctx.browser_context.switch_tab(new_tab)
                msg += " - new tab opened and switched"
            return ActionResult(extracted_content=msg, include_in_memory=True)

        def input_text(args, selector_map):
            element = get_element(args.get("index"), selector_map)
            text = args.get("text", "")
            get_page().input_text(element, text)
            return ActionResult(
                extracted_content=redact_input_message(args.get("index"), text, element),
                include_in_memory=True,
            )

        def switch_tab(args, _selector_map):
            tab_id = int(args["tab_id"])
            ctx.browser_context.switch_tab(tab_id)
            return ActionResult(extracted_content=f"Switched to tab {tab_id}", include_in_memory=True)

        def open_tab(args, _selector_map):
            url = args["url"]
            ctx.browser_context.open_tab(url)
            return ActionResult(extracted_content=f"Opened tab with {url}", include_in_memory=True)

        def close_tab(args, _selector_map):
            tab_id = int(args["tab_id"])
            ctx.browser_context.close_tab(tab_id)
            return ActionResult(extracted_content=f"Closed tab {tab_id}", include_in_memory=True)

        def cache_content(args, _selector_map):
            content = args.get("content", "")
            msg = wrap_untrusted_content(f"Cached findings: {content}")
            return ActionResult(extracted_content=msg, include_in_memory=True)

        def scroll_to_percent(args, selector_map):
            y_percent = int(args.get("yPercent", args.get("percent", 0)))
            element = optional_scroll_element(args, selector_map)
            region = get_page().scroll_to_percent(y_percent, element)
            if region is None:
                return ActionResult(
                    extracted_content="No scrollable region found",
                    include_in_memory=True,
                )
            label = _scroll_result_label(region)
            return ActionResult(
                extracted_content=f"Scrolled {label} to {y_percent}%",
                include_in_memory=True,
                interacted_element=_history_element_from_scroll_region(region),
            )

        def scroll_to_top(args, selector_map):
            element = optional_scroll_element(args, selector_map)
            resolved = get_page().resolve_scroll_target(element)
            if not resolved:
                return ActionResult(
                    extracted_content="No scrollable region found",
                    include_in_memory=True,
                )
            region, _handle = resolved
            interacted = _history_element_from_scroll_region(region)
            if region.at_top:
                return ActionResult(
                    extracted_content=f"{_scroll_result_label(region)} already at top",
                    include_in_memory=True,
                    interacted_element=interacted,
                )
            get_page().scroll_to_percent(0, element)
            return ActionResult(
                extracted_content=f"Scrolled {_scroll_result_label(region)} to top",
                include_in_memory=True,
                interacted_element=interacted,
            )

        def scroll_to_bottom(args, selector_map):
            element = optional_scroll_element(args, selector_map)
            resolved = get_page().resolve_scroll_target(element)
            if not resolved:
                return ActionResult(
                    extracted_content="No scrollable region found",
                    include_in_memory=True,
                )
            region, _handle = resolved
            interacted = _history_element_from_scroll_region(region)
            if region.at_bottom:
                return ActionResult(
                    extracted_content=f"{_scroll_result_label(region)} already at bottom",
                    include_in_memory=True,
                    interacted_element=interacted,
                )
            get_page().scroll_to_percent(100, element)
            return ActionResult(
                extracted_content=f"Scrolled {_scroll_result_label(region)} to bottom",
                include_in_memory=True,
                interacted_element=interacted,
            )

        def previous_page(args, selector_map):
            element = optional_scroll_element(args, selector_map)
            resolved = get_page().resolve_scroll_target(element)
            if not resolved:
                return ActionResult(
                    extracted_content="No scrollable region found",
                    include_in_memory=True,
                )
            region, _handle = resolved
            interacted = _history_element_from_scroll_region(region)
            if region.at_top:
                return ActionResult(
                    extracted_content=f"{_scroll_result_label(region)} already at top",
                    include_in_memory=True,
                    interacted_element=interacted,
                )
            get_page().scroll_to_previous_page(element)
            return ActionResult(
                extracted_content=f"Scrolled {_scroll_result_label(region)} to previous page",
                include_in_memory=True,
                interacted_element=interacted,
            )

        def next_page(args, selector_map):
            element = optional_scroll_element(args, selector_map)
            resolved = get_page().resolve_scroll_target(element)
            if not resolved:
                return ActionResult(
                    extracted_content="No scrollable region found",
                    include_in_memory=True,
                )
            region, _handle = resolved
            interacted = _history_element_from_scroll_region(region)
            if region.at_bottom:
                return ActionResult(
                    extracted_content=f"{_scroll_result_label(region)} already at bottom",
                    include_in_memory=True,
                    interacted_element=interacted,
                )
            get_page().scroll_to_next_page(element)
            return ActionResult(
                extracted_content=f"Scrolled {_scroll_result_label(region)} to next page",
                include_in_memory=True,
                interacted_element=interacted,
            )

        def scroll_to_text(args, _selector_map):
            text = args["text"]
            nth = int(args.get("nth", 1))
            found = get_page().scroll_to_text(text, nth)
            msg = (
                f"Scrolled to text '{text}' (occurrence {nth})"
                if found
                else f"Text '{text}' (occurrence {nth}) not found"
            )
            if not found:
                return ActionResult(error=msg, include_in_memory=True)
            return ActionResult(extracted_content=msg, include_in_memory=True)

        def send_keys(args, _selector_map):
            keys = args["keys"]
            get_page().send_keys(keys)
            return ActionResult(extracted_content=f"Sent keys: {keys}", include_in_memory=True)

        def get_dropdown_options(args, selector_map):
            element = get_element(args.get("index"), selector_map)
            options = get_page().get_dropdown_options(element)
            if options:
                formatted = [
                    f"{opt['index']}: text={json.dumps(opt['text'])}"
                    for opt in options
                ]
                msg = "\n".join(formatted) + "\nUse the exact text in select_dropdown_option"
                return ActionResult(extracted_content=msg, include_in_memory=True)
            return ActionResult(extracted_content="No options found", include_in_memory=True)

        def select_dropdown_option(args, selector_map):
            element = get_element(args.get("index"), selector_map)
            if element.tag_name.lower() != "select":
                return ActionResult(
                    error=f"Element {args.get('index')} is not a select element",
                    include_in_memory=True,
                )
            text = args["text"]
            result = get_page().select_dropdown_option(element, text)
            if result != "ok":
                return ActionResult(error=result, include_in_memory=True)
            return ActionResult(
                extracted_content=f"Selected option in dropdown {args.get('index')}",
                include_in_memory=True,
            )

        handlers.update({
            "done": done,
            "search_google": search_google,
            "go_to_url": go_to_url,
            "go_back": go_back,
            "wait": wait_action,
            "click_element": click_element,
            "input_text": input_text,
            "switch_tab": switch_tab,
            "open_tab": open_tab,
            "close_tab": close_tab,
            "cache_content": cache_content,
            "scroll_to_percent": scroll_to_percent,
            "scroll_to_top": scroll_to_top,
            "scroll_to_bottom": scroll_to_bottom,
            "previous_page": previous_page,
            "next_page": next_page,
            "scroll_to_text": scroll_to_text,
            "send_keys": send_keys,
            "get_dropdown_options": get_dropdown_options,
            "select_dropdown_option": select_dropdown_option,
        })

        return NavigatorActionRegistry(handlers)
