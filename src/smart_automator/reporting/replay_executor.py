from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Locator, Page as PlaywrightPage

from ..agent.context import ActionResult
from ..browser.context import BrowserContext
from ..browser.locators import click_with_fallback
from .replay_script import (
    _playwright_keyboard_key,
    _split_replay_locator_candidates,
    assert_locator_matches_identity,
    resolve_replay_locator,
)

_INTERACTIVE_ACTIONS = frozenset({
    "click_element",
    "input_text",
    "select_dropdown_option",
})

_IDENTITY_GATE_ACTIONS = frozenset({
    "click_element",
    "input_text",
    "select_dropdown_option",
})

_REQUIRED_ELEMENT_LOCATOR_ACTIONS = frozenset({
    "click_element",
    "input_text",
    "select_dropdown_option",
    "scroll_to_text",
    "get_dropdown_options",
})

_OPTIONAL_ELEMENT_LOCATOR_ACTIONS = frozenset({
    "scroll_to_percent",
    "scroll_to_top",
    "scroll_to_bottom",
    "previous_page",
    "next_page",
})


def _needs_settle_wait(step: dict[str, Any]) -> bool:
    return step.get("action") in _INTERACTIVE_ACTIONS


def _resolve_locator(
    page: PlaywrightPage,
    step: dict[str, Any],
    *,
    poll_timeout_seconds: float = 15.0,
) -> Locator:
    return resolve_replay_locator(
        page,
        step,
        poll_timeout_seconds=poll_timeout_seconds,
    )


def _step_has_locator_candidates(step: dict[str, Any]) -> bool:
    identity, positional = _split_replay_locator_candidates(step)
    return bool(identity or positional)


def _resolve_step_locator(
    page: PlaywrightPage,
    step: dict[str, Any],
) -> Locator | None:
    action = step.get("action", "")
    if action in _REQUIRED_ELEMENT_LOCATOR_ACTIONS:
        return _resolve_locator(page, step)
    if action in _OPTIONAL_ELEMENT_LOCATOR_ACTIONS:
        if not _step_has_locator_candidates(step):
            return None
        return _resolve_locator(page, step)
    return None


def _execute_replay_step(page: PlaywrightPage, browser_context: BrowserContext, step: dict[str, Any]) -> ActionResult:
    action = step.get("action", "")
    args = step.get("args") or {}
    action_name = action

    try:
        if action == "go_to_url":
            url = str(args.get("url", ""))
            browser_context.navigate_to(url)
            return ActionResult(
                extracted_content=f"Navigated to {url}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "search_google":
            query = args.get("query") or args.get("text") or ""
            browser_context.navigate_to(f"https://www.google.com/search?q={query}")
            return ActionResult(
                extracted_content=f"Searched Google for: {query}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "go_back":
            page.go_back()
            return ActionResult(extracted_content="Went back", include_in_memory=True, action_name=action_name)
        if action == "wait":
            seconds = float(args.get("seconds") or args.get("duration") or 3)
            page.wait_for_timeout(int(seconds * 1000))
            return ActionResult(
                extracted_content=f"Waited {seconds:g} seconds",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "send_keys":
            page.keyboard.press(_playwright_keyboard_key(str(args.get("keys", ""))))
            return ActionResult(
                extracted_content=f"Sent keys: {args.get('keys', '')}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "open_tab":
            url = str(args.get("url", ""))
            browser_context.open_tab(url)
            return ActionResult(
                extracted_content=f"Opened tab: {url}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "switch_tab":
            tab_id = int(args.get("tab_id", 0))
            browser_context.switch_tab(tab_id)
            return ActionResult(
                extracted_content=f"Switched to tab {tab_id}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "close_tab":
            tab_id = browser_context.current_page_id
            if tab_id is not None:
                browser_context.close_tab(tab_id)
            return ActionResult(extracted_content="Closed tab", include_in_memory=True, action_name=action_name)

        locator = _resolve_step_locator(page, step)
        if locator is not None and action in _IDENTITY_GATE_ACTIONS:
            assert_locator_matches_identity(locator, step)

        if action == "click_element":
            assert locator is not None
            click_with_fallback(
                locator,
                verify=lambda: assert_locator_matches_identity(locator, step),
            )
            return ActionResult(
                extracted_content=f"Clicked {step.get('element_label') or 'element'}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "input_text":
            assert locator is not None
            text = str(args.get("text", ""))
            locator.fill(text)
            return ActionResult(
                extracted_content=f"Typed into element",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "select_dropdown_option":
            assert locator is not None
            text = str(args.get("text", ""))
            locator.select_option(label=text)
            return ActionResult(
                extracted_content=f"Selected option: {text}",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "scroll_to_percent":
            percent = int(args.get("yPercent") or args.get("percent") or 0)
            if locator is not None:
                locator.evaluate(
                    "(el, pct) => el.scrollTo({ top: (el.scrollHeight - el.clientHeight) * pct / 100 })",
                    percent,
                )
            else:
                page.evaluate(
                    "(pct) => window.scrollTo(0, document.body.scrollHeight * pct / 100)",
                    percent,
                )
            return ActionResult(
                extracted_content=f"Scrolled to {percent}%",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "scroll_to_top":
            if locator is not None:
                locator.evaluate("el => el.scrollTo({ top: 0 })")
            else:
                page.evaluate("() => window.scrollTo(0, 0)")
            return ActionResult(extracted_content="Scrolled to top", include_in_memory=True, action_name=action_name)
        if action == "scroll_to_bottom":
            if locator is not None:
                locator.evaluate("el => el.scrollTo({ top: el.scrollHeight })")
            else:
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            return ActionResult(
                extracted_content="Scrolled to bottom",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "previous_page":
            if locator is not None:
                locator.evaluate("el => el.scrollBy({ top: -el.clientHeight })")
            else:
                page.evaluate("() => window.scrollBy(0, -window.innerHeight)")
            return ActionResult(extracted_content="Previous page", include_in_memory=True, action_name=action_name)
        if action == "next_page":
            if locator is not None:
                locator.evaluate("el => el.scrollBy({ top: el.clientHeight })")
            else:
                page.evaluate("() => window.scrollBy(0, window.innerHeight)")
            return ActionResult(
                extracted_content="Next page",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "scroll_to_text":
            assert locator is not None
            locator.scroll_into_view_if_needed()
            return ActionResult(
                extracted_content="Scrolled to text",
                include_in_memory=True,
                action_name=action_name,
            )
        if action == "get_dropdown_options":
            return ActionResult(
                extracted_content="Read dropdown options (replay)",
                include_in_memory=True,
                action_name=action_name,
            )

        return ActionResult(error=f"Unsupported replay action: {action}", action_name=action_name)
    except Exception as exc:
        return ActionResult(error=str(exc), action_name=action_name)


def execute_replay_steps(
    browser_context: BrowserContext,
    steps: list[dict[str, Any]],
    *,
    action_retry_wait_seconds: float = 0.0,
    stopped: bool = False,
    paused: bool = False,
) -> list[ActionResult]:
    results: list[ActionResult] = []
    if not steps:
        return results

    page = browser_context.get_current_page().playwright_page

    for step in steps:
        if stopped or paused:
            break

        result = _execute_replay_step(page, browser_context, step)
        if (
            result.error
            and action_retry_wait_seconds > 0
            and not stopped
            and not paused
        ):
            time.sleep(action_retry_wait_seconds)
            if not stopped and not paused:
                page = browser_context.get_current_page().playwright_page
                result = _execute_replay_step(page, browser_context, step)

        results.append(result)
        if result.error:
            break
        if _needs_settle_wait(step):
            browser_context.get_current_page().wait_for_page_stable()

    return results
