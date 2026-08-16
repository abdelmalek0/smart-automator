from __future__ import annotations

from typing import Any

from ..browser.locators import (
    CLICK_RESOLVED_HELPER,
    DEFAULT_RESOLVE_POLL_INTERVAL,
    DEFAULT_RESOLVE_POLL_SECONDS,
    NTH_RESOLVE_HELPER,
    RESOLVE_UNIQUE_HELPER,
    ReplayLocatorError,
    assert_locator_matches_identity,
    css_has_identity_attrs,
    element_accessible_name as _element_accessible_name,
    format_locator_expr,
    is_unstable_id,
    playwright_locator_expr,
    resolve_replay_locator,
    sanitize_css_selector,
    split_locator_candidates,
    step_has_recorded_identity,
)

DOM_ACTIONS = frozenset({
    "click_element",
    "input_text",
    "get_dropdown_options",
    "select_dropdown_option",
    "scroll_to_percent",
    "scroll_to_top",
    "scroll_to_bottom",
    "previous_page",
    "next_page",
    "scroll_to_text",
})

NON_REPLAYABLE = frozenset({"done", "cache_content"})
_NON_REPLAYABLE_VERIFICATION = frozenset({"failed"})
_LOCATOR_ACTIONS = frozenset({
    "click_element",
    "input_text",
    "select_dropdown_option",
    "scroll_to_text",
    "get_dropdown_options",
    "scroll_to_percent",
    "scroll_to_top",
    "scroll_to_bottom",
    "previous_page",
    "next_page",
})

# Compatibility aliases for existing tests and callers.
_is_unstable_flutter_id = is_unstable_id
_sanitize_css_for_flutter = sanitize_css_selector
_css_has_identity_attrs = css_has_identity_attrs
_step_has_recorded_identity = step_has_recorded_identity
_split_replay_locator_candidates = split_locator_candidates
_playwright_locator = playwright_locator_expr
_DEFAULT_RESOLVE_POLL_SECONDS = DEFAULT_RESOLVE_POLL_SECONDS
_DEFAULT_RESOLVE_POLL_INTERVAL = DEFAULT_RESOLVE_POLL_INTERVAL


def _format_element_label(element: dict[str, Any] | None) -> str | None:
    if not element:
        return None
    tag = element.get("tagName") or element.get("tag_name") or "element"
    attrs = element.get("attributes") or {}
    for key in ("aria-label", "name", "placeholder", "type"):
        value = attrs.get(key)
        if value:
            return f'<{tag} {key}="{value}">'
    accessible_name = _element_accessible_name(element)
    if accessible_name:
        return f"<{tag} ({accessible_name[:40]})>"
    element_id = attrs.get("id")
    if element_id and not is_unstable_id(element_id):
        return f"<{tag}#{element_id}>"
    text_hint = attrs.get("value") or attrs.get("title")
    if text_hint:
        return f"<{tag} ({text_hint[:40]})>"
    if element_id:
        return f"<{tag}#{element_id}>"
    return f"<{tag}>"


def build_replay_action_args(
    action: str,
    args: dict[str, Any],
    element: dict[str, Any] | None,
) -> dict[str, Any]:
    replay_args = dict(args)
    if action in DOM_ACTIONS and element:
        xpath = element.get("xpath")
        css_selector = element.get("cssSelector") or element.get("css_selector")
        if xpath:
            replay_args["xpath"] = xpath
        if css_selector:
            replay_args["css_selector"] = css_selector
        if replay_args.get("xpath") or replay_args.get("css_selector"):
            replay_args.pop("index", None)
    return replay_args


def _build_replay_args(
    action: str,
    args: dict[str, Any],
    element: dict[str, Any] | None,
) -> dict[str, Any]:
    return build_replay_action_args(action, args, element)


def _has_replay_failure(entry: dict[str, Any]) -> bool:
    if entry.get("error"):
        return True
    return entry.get("verification_status") in _NON_REPLAYABLE_VERIFICATION


def _is_replayable(entry: dict[str, Any]) -> bool:
    action = entry.get("action", "")
    if action in NON_REPLAYABLE:
        return False
    return not _has_replay_failure(entry)


def build_replay_steps(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for entry in timeline:
        if not _is_replayable(entry):
            continue
        action = entry["action"]
        args = dict(entry.get("args") or {})
        element = entry.get("element")
        element_label = _format_element_label(element)
        replay_args = _build_replay_args(action, args, element)
        steps.append(
            {
                "index": len(steps) + 1,
                "action": action,
                "args": replay_args,
                "element": element,
                "url": entry.get("url"),
                "page_title": entry.get("page_title"),
                "element_label": element_label,
                "verification_status": entry.get("verification_status"),
                "outcome": entry.get("extracted_content"),
                "source": entry.get("source"),
            }
        )
    return steps


def _replay_locator_candidates(step: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    identity, positional = split_locator_candidates(step)
    return identity + positional


def _playwright_keyboard_key(keys: str) -> str:
    normalized = keys.strip().lower().replace("return", "enter")
    key_map = {
        "enter": "Enter",
        "backspace": "Backspace",
        "tab": "Tab",
        "escape": "Escape",
        "space": "Space",
        "arrowleft": "ArrowLeft",
        "arrowright": "ArrowRight",
        "arrowup": "ArrowUp",
        "arrowdown": "ArrowDown",
        "pagedown": "PageDown",
        "pageup": "PageUp",
        "delete": "Delete",
    }
    parts = normalized.split("+")
    if len(parts) > 1:
        mapped = [key_map.get(part, part.title()) for part in parts]
        return "+".join(mapped)
    return key_map.get(normalized, keys)


def _locator_builders_source(step: dict[str, Any]) -> str:
    identity, positional = split_locator_candidates(step)
    candidates = identity or positional
    if not candidates:
        return "[]"
    lines = ["["]
    for kind, params in candidates:
        expr = format_locator_expr(kind, params, root="page")
        lines.append(f"            lambda: {expr},")
    lines.append("        ]")
    return "\n".join(lines)


def _needs_element_locator(step: dict[str, Any]) -> bool:
    action = step.get("action", "")
    if action not in _LOCATOR_ACTIONS:
        return False
    identity, positional = split_locator_candidates(step)
    if action in {
        "scroll_to_percent",
        "scroll_to_top",
        "scroll_to_bottom",
        "previous_page",
        "next_page",
    }:
        return bool(identity or positional)
    return True


def _format_playwright_step(step: dict[str, Any]) -> str | None:
    action = step["action"]
    args = step.get("args") or {}
    use_resolver = _needs_element_locator(step)
    locator = "locator" if use_resolver else playwright_locator_expr(step)

    if action == "go_to_url":
        return f"page.goto({args.get('url', '')!r})"
    if action == "search_google":
        query = args.get("query") or args.get("text") or ""
        return f'page.goto(f"https://www.google.com/search?q={query}")'
    if action == "go_back":
        return "page.go_back()"
    if action == "wait":
        seconds = int(args.get("seconds") or args.get("duration") or 3)
        return f"page.wait_for_timeout({seconds * 1000})"

    prefix = ""
    if use_resolver:
        prefix = f"locator = resolve_unique(page, {_locator_builders_source(step)})\n"

    if action == "click_element":
        return f"{prefix}click_resolved({locator})"
    if action == "input_text":
        return f"{prefix}{locator}.fill({args.get('text', '')!r})"
    if action == "select_dropdown_option":
        text = args.get("text", "")
        return f"{prefix}{locator}.select_option(label={text!r})"
    if action == "send_keys":
        return f'page.keyboard.press({_playwright_keyboard_key(str(args.get("keys", "")))!r})'
    if action == "scroll_to_percent":
        percent = int(args.get("yPercent") or args.get("percent") or 0)
        if use_resolver:
            return (
                f"{prefix}{locator}.evaluate("
                f"'el => el.scrollTo({{ top: (el.scrollHeight - el.clientHeight) * {percent} / 100 }})')"
            )
        return (
            "page.evaluate("
            f"\"() => window.scrollTo(0, document.body.scrollHeight * {percent} / 100)\""
            ")"
        )
    if action == "scroll_to_top":
        if use_resolver:
            return f"{prefix}{locator}.evaluate('el => el.scrollTo({{ top: 0 }})')"
        return "page.evaluate('() => window.scrollTo(0, 0)')"
    if action == "scroll_to_bottom":
        if use_resolver:
            return f"{prefix}{locator}.evaluate('el => el.scrollTo({{ top: el.scrollHeight }})')"
        return "page.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')"
    if action == "previous_page":
        if use_resolver:
            return f"{prefix}{locator}.evaluate('el => el.scrollBy({{ top: -el.clientHeight }})')"
        return "page.evaluate('() => window.scrollBy(0, -window.innerHeight)')"
    if action == "next_page":
        if use_resolver:
            return f"{prefix}{locator}.evaluate('el => el.scrollBy({{ top: el.clientHeight }})')"
        return "page.evaluate('() => window.scrollBy(0, window.innerHeight)')"
    if action == "scroll_to_text":
        return f"{prefix}{locator}.scroll_into_view_if_needed()"
    if action == "open_tab":
        url = args.get("url", "")
        return f"page = context.new_page(); page.goto({url!r})"
    if action == "switch_tab":
        tab_id = int(args.get("tab_id", 0))
        return f"page = context.pages[{tab_id}]"
    if action == "close_tab":
        return "page.close()"
    if action == "get_dropdown_options":
        return f"{prefix}# read-only: {locator}.locator('option').all_inner_texts()"
    return None


def format_replay_script(
    steps: list[dict[str, Any]],
    *,
    run_id: str,
    status: str,
    skipped_failed: int = 0,
    skipped_done: int = 0,
) -> str:
    lines = [
        f'"""Playwright replay — run {run_id[:8]} ({status})."""',
        "from playwright.sync_api import sync_playwright",
        "",
        "",
        NTH_RESOLVE_HELPER,
        "",
        "",
        RESOLVE_UNIQUE_HELPER,
        "",
        "",
        CLICK_RESOLVED_HELPER,
        "",
        "",
        "def run():",
        "    with sync_playwright() as p:",
        "        browser = p.chromium.launch(headless=False)",
        "        context = browser.new_context()",
        "        page = context.new_page()",
        "",
    ]
    if skipped_failed or skipped_done:
        parts = []
        if skipped_failed:
            parts.append(f"{skipped_failed} errored")
        if skipped_done:
            parts.append(f"{skipped_done} done")
        lines.append(f"        # Excluded: {', '.join(parts)}")
        lines.append("")

    if not steps:
        lines.extend([
            "        pass",
            "        browser.close()",
            "",
            "",
            'if __name__ == "__main__":',
            "    run()",
            "",
        ])
        return "\n".join(lines)

    for step in steps:
        comment = f"        # {step['index']}. {step['action']}"
        if step.get("element_label"):
            comment += f" → {step['element_label']}"
        lines.append(comment)
        code = _format_playwright_step(step)
        if code:
            for code_line in code.splitlines():
                lines.append(f"        {code_line}")
        else:
            lines.append(f"        # unsupported action: {step['action']}")
        lines.append("")

    lines.extend([
        "        browser.close()",
        "",
        "",
        'if __name__ == "__main__":',
        "    run()",
        "",
    ])
    return "\n".join(lines)


def count_skipped_actions(timeline: list[dict[str, Any]]) -> tuple[int, int]:
    skipped_failed = 0
    skipped_done = 0
    for entry in timeline:
        action = entry.get("action", "")
        if action == "done":
            skipped_done += 1
        elif _has_replay_failure(entry):
            skipped_failed += 1
    return skipped_failed, skipped_done
