from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.parse import urlparse

from ..agent.context import ActionResult, AgentContext
from ..agent.messages.utils import wrap_untrusted_content
from ..browser.dom import DOMElementNode, branch_hash_is_subset_of, calc_branch_path_hash_set
from ..browser.history import convert_dom_element_to_history_element, is_file_uploader
from ..browser.views import BrowserState, URLNotAllowedError
from .schemas import Action


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


def _action_will_navigate(action: Action, page_url: str) -> bool:
    if action.name in ("go_back", "search_google", "open_tab"):
        return True
    if action.name == "go_to_url":
        url = action.args.get("url", "")
        return _normalize_url(url) != _normalize_url(page_url)
    return False


def _should_break_action_sequence(
    action: Action,
    *,
    page_url: str,
    page_title: str,
    cached_hashes: set[str],
    new_url: str,
    new_title: str,
    new_hashes: set[str],
) -> bool:
    if action.name in _NAVIGATION_ACTIONS:
        return True
    if action.name in ("click_element", "send_keys"):
        if new_url != page_url or new_title != page_title:
            return True
        return not branch_hash_is_subset_of(new_hashes, cached_hashes)
    if action.name in _PAGE_STATE_CHANGING_ACTIONS:
        return True
    return False


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

    def execute_multi(
        self,
        actions: list[Action],
        context: AgentContext,
        browser_state: BrowserState | None = None,
    ) -> list[ActionResult]:
        results: list[ActionResult] = []
        browser_context = context.browser_context
        page = browser_context.get_current_page()

        if browser_state is None:
            browser_state = browser_context.get_state(show_highlights=True)

        if not actions:
            return results

        selector_map = dict(browser_state.selector_map)
        cached_hashes = calc_branch_path_hash_set(selector_map)
        page_url = browser_state.url
        page_title = browser_state.title
        action_delay = context.options.action_delay_seconds
        err_count = 0

        for i, action in enumerate(actions):
            if context.paused or context.stopped:
                break

            if i > 0 and self.has_index(action.name) and action.index is not None:
                new_state = browser_context.get_state(show_highlights=False)
                new_hashes = calc_branch_path_hash_set(new_state.selector_map)
                if not branch_hash_is_subset_of(new_hashes, cached_hashes):
                    msg = f"Something new appeared after action {i} / {len(actions)}"
                    results.append(ActionResult(extracted_content=msg, include_in_memory=True))
                    break
                selector_map = new_state.selector_map
                cached_hashes = new_hashes

            cached_dom = page.get_cached_state()
            if cached_dom is not None:
                selector_map = cached_dom.selector_map
            elif action.index is not None and action.index not in selector_map:
                fresh = page.get_dom_state(show_highlights=False, wait_for_stable=False)
                selector_map = fresh.selector_map

            if _action_will_navigate(action, page_url):
                browser_context.remove_highlight()

            result = self.execute(action, selector_map)
            if (
                self.has_index(action.name)
                and action.index is not None
                and action.index in selector_map
            ):
                result.interacted_element = convert_dom_element_to_history_element(
                    selector_map[action.index]
                )
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
            if result.error:
                err_count += 1
                if err_count >= 3:
                    break
                continue

            post_action_state = None
            needs_post_action_snapshot = self.has_index(action.name) and action.index is not None
            needs_next_action_check = (
                i < len(actions) - 1
                and self.has_index(actions[i + 1].name)
                and actions[i + 1].index is not None
            )
            if needs_post_action_snapshot or needs_next_action_check:
                post_action_state = browser_context.get_state(show_highlights=False)
                selector_map = post_action_state.selector_map
                cached_hashes = calc_branch_path_hash_set(selector_map)
                page_url = post_action_state.url
                page_title = post_action_state.title

            if needs_next_action_check and post_action_state is not None:
                new_hashes = calc_branch_path_hash_set(post_action_state.selector_map)
                if _should_break_action_sequence(
                    action,
                    page_url=page_url,
                    page_title=page_title,
                    cached_hashes=cached_hashes,
                    new_url=post_action_state.url,
                    new_title=post_action_state.title,
                    new_hashes=new_hashes,
                ):
                    msg = f"Action sequence stopped after action {i + 1}/{len(actions)} due to page change"
                    results.append(ActionResult(extracted_content=msg, include_in_memory=True))
                    break

            if i < len(actions) - 1:
                time.sleep(action_delay)
            else:
                page.wait_for_page_stable()

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
            seconds = int(args.get("seconds", 3))
            time.sleep(seconds)
            return ActionResult(extracted_content=f"Waited {seconds} seconds", include_in_memory=True)

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
                extracted_content=f"Typed '{text}' into element {args.get('index')}",
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
            element = optional_element(args.get("index"), selector_map)
            get_page().scroll_to_percent(y_percent, element)
            return ActionResult(extracted_content=f"Scrolled to {y_percent}%", include_in_memory=True)

        def scroll_to_top(args, selector_map):
            element = optional_element(args.get("index"), selector_map)
            get_page().scroll_to_percent(0, element)
            return ActionResult(extracted_content="Scrolled to top", include_in_memory=True)

        def scroll_to_bottom(args, selector_map):
            element = optional_element(args.get("index"), selector_map)
            get_page().scroll_to_percent(100, element)
            return ActionResult(extracted_content="Scrolled to bottom", include_in_memory=True)

        def previous_page(args, selector_map):
            element = optional_element(args.get("index"), selector_map)
            if element:
                scroll_top, _, scroll_height = get_page().get_element_scroll_info(element)
                if scroll_top == 0:
                    return ActionResult(
                        extracted_content=f"Element {args.get('index')} already at top",
                        include_in_memory=True,
                    )
            else:
                scroll_y, viewport_h, _ = get_page().get_scroll_info()
                if scroll_y == 0:
                    return ActionResult(extracted_content="Page already at top", include_in_memory=True)
            get_page().scroll_to_previous_page(element)
            return ActionResult(extracted_content="Scrolled to previous page", include_in_memory=True)

        def next_page(args, selector_map):
            element = optional_element(args.get("index"), selector_map)
            if element:
                scroll_top, client_h, scroll_height = get_page().get_element_scroll_info(element)
                if scroll_top + client_h >= scroll_height:
                    return ActionResult(
                        extracted_content=f"Element {args.get('index')} already at bottom",
                        include_in_memory=True,
                    )
            else:
                scroll_y, viewport_h, scroll_height = get_page().get_scroll_info()
                if scroll_y + viewport_h >= scroll_height:
                    return ActionResult(extracted_content="Page already at bottom", include_in_memory=True)
            get_page().scroll_to_next_page(element)
            return ActionResult(extracted_content="Scrolled to next page", include_in_memory=True)

        def scroll_to_text(args, _selector_map):
            text = args["text"]
            nth = int(args.get("nth", 1))
            found = get_page().scroll_to_text(text, nth)
            msg = (
                f"Scrolled to text '{text}' (occurrence {nth})"
                if found
                else f"Text '{text}' (occurrence {nth}) not found"
            )
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
                extracted_content=f"Selected '{text}' in dropdown {args.get('index')}",
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
