from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Locator, Page as PlaywrightPage

_FLUTTER_ID_IN_CSS = re.compile(r'\[id="flt-semantic-node-\d+"\]')

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


def _element_accessible_name(element: dict[str, Any] | None) -> str | None:
    if not element:
        return None
    raw = element.get("accessibleName", element.get("accessible_name"))
    if raw is None:
        return None
    name = str(raw).strip()
    return name or None


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
    if element_id and not _is_unstable_flutter_id(element_id):
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


def _is_replayable(entry: dict[str, Any]) -> bool:
    action = entry.get("action", "")
    if action in NON_REPLAYABLE:
        return False
    return not entry.get("error")


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


def _element_attrs(step: dict[str, Any]) -> dict[str, str]:
    element = step.get("element") or {}
    attrs = element.get("attributes") or {}
    return {str(key): str(value) for key, value in attrs.items()}


def _is_unstable_flutter_id(element_id: str) -> bool:
    return element_id.startswith("flt-semantic-node-")


def _sanitize_css_for_flutter(css: str) -> str:
    return _FLUTTER_ID_IN_CSS.sub("", css)


def _normalize_xpath(xpath: str) -> str:
    xpath_target = xpath if xpath.startswith(("xpath=", "/")) else f"xpath=/{xpath.lstrip('/')}"
    if not xpath_target.startswith("xpath="):
        xpath_target = f"xpath={xpath_target}"
    return xpath_target


def _replay_locator_candidates(step: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    args = step.get("args") or {}
    attrs = _element_attrs(step)
    element = step.get("element") or {}
    candidates: list[tuple[str, dict[str, Any]]] = []

    if label := attrs.get("aria-label"):
        candidates.append(("label", {"label": label}))
    if placeholder := attrs.get("placeholder"):
        candidates.append(("placeholder", {"placeholder": placeholder}))

    role = attrs.get("role")
    accessible_name = _element_accessible_name(element)
    if role and accessible_name:
        candidates.append(("role", {"role": role, "name": accessible_name}))

    element_id = attrs.get("id")
    css = args.get("css_selector")
    xpath = args.get("xpath")

    if element_id and _is_unstable_flutter_id(element_id):
        if css:
            candidates.append(("css", {"selector": _sanitize_css_for_flutter(css)}))
        if xpath:
            candidates.append(("xpath", {"xpath": _normalize_xpath(xpath)}))
    elif element_id:
        candidates.append(("css", {"selector": f"#{element_id}"}))

    if css and not any(kind == "css" for kind, _ in candidates):
        candidates.append(("css", {"selector": css}))
    if xpath and not any(kind == "xpath" for kind, _ in candidates):
        candidates.append(("xpath", {"xpath": _normalize_xpath(xpath)}))
    if (text := args.get("text")) and step.get("action") == "scroll_to_text":
        candidates.append(("text", {"text": text}))
    if index := args.get("index"):
        candidates.append(("index", {"index": index}))

    return candidates


def _apply_replay_locator(page: PlaywrightPage, kind: str, params: dict[str, Any]) -> Locator:
    if kind == "label":
        return page.get_by_label(params["label"], exact=True)
    if kind == "placeholder":
        return page.get_by_placeholder(params["placeholder"], exact=True)
    if kind == "role":
        return page.get_by_role(params["role"], name=params["name"], exact=True)
    if kind == "css":
        return page.locator(params["selector"])
    if kind == "xpath":
        return page.locator(params["xpath"])
    if kind == "text":
        return page.get_by_text(params["text"], exact=True)
    if kind == "index":
        return page.locator(f'[data-sa-index="{params["index"]}"]')
    return page.locator("body")


def resolve_replay_locator(page: PlaywrightPage, step: dict[str, Any]) -> Locator:
    candidates = _replay_locator_candidates(step)
    if not candidates:
        return page.locator("body")

    last_locator: Locator | None = None
    for kind, params in candidates:
        locator = _apply_replay_locator(page, kind, params)
        last_locator = locator
        try:
            if locator.count() == 1:
                return locator
        except Exception:
            continue

    return last_locator if last_locator is not None else page.locator("body")


def _format_replay_locator_expr(kind: str, params: dict[str, Any]) -> str:
    if kind == "label":
        return f'page.get_by_label({params["label"]!r}, exact=True)'
    if kind == "placeholder":
        return f'page.get_by_placeholder({params["placeholder"]!r}, exact=True)'
    if kind == "role":
        return (
            f'page.get_by_role({params["role"]!r}, name={params["name"]!r}, exact=True)'
        )
    if kind == "css":
        return f"page.locator({params['selector']!r})"
    if kind == "xpath":
        return f"page.locator({_normalize_xpath(params['xpath'])!r})"
    if kind == "text":
        return f'page.get_by_text({params["text"]!r}, exact=True)'
    if kind == "index":
        index = params["index"]
        selector = f'[data-sa-index="{index}"]'
        return f"page.locator({selector!r})  # unstable highlight index"
    return "page.locator('body')  # fallback — no stable locator captured"


def _playwright_locator(step: dict[str, Any]) -> str:
    candidates = _replay_locator_candidates(step)
    if not candidates:
        return "page.locator('body')  # fallback — no stable locator captured"
    kind, params = candidates[0]
    return _format_replay_locator_expr(kind, params)


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


def _format_playwright_step(step: dict[str, Any]) -> str | None:
    action = step["action"]
    args = step.get("args") or {}
    locator = _playwright_locator(step)

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
    if action == "click_element":
        return f"{locator}.click()"
    if action == "input_text":
        return f"{locator}.fill({args.get('text', '')!r})"
    if action == "select_dropdown_option":
        text = args.get("text", "")
        return f"{locator}.select_option(label={text!r})"
    if action == "send_keys":
        return f'page.keyboard.press({_playwright_keyboard_key(str(args.get("keys", "")))!r})'
    if action == "scroll_to_percent":
        percent = int(args.get("yPercent") or args.get("percent") or 0)
        if "locator(" in locator and "body" not in locator:
            return f"{locator}.evaluate('el => el.scrollTo({{ top: (el.scrollHeight - el.clientHeight) * {percent} / 100 }})')"
        return (
            "page.evaluate("
            f"\"() => window.scrollTo(0, document.body.scrollHeight * {percent} / 100)\""
            ")"
        )
    if action == "scroll_to_top":
        if "locator(" in locator and "body" not in locator:
            return f"{locator}.evaluate('el => el.scrollTo({{ top: 0 }})')"
        return "page.evaluate('() => window.scrollTo(0, 0)')"
    if action == "scroll_to_bottom":
        if "locator(" in locator and "body" not in locator:
            return f"{locator}.evaluate('el => el.scrollTo({{ top: el.scrollHeight }})')"
        return "page.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')"
    if action == "previous_page":
        if "locator(" in locator and "body" not in locator:
            return f"{locator}.evaluate('el => el.scrollBy({{ top: -el.clientHeight }})')"
        return "page.evaluate('() => window.scrollBy(0, -window.innerHeight)')"
    if action == "next_page":
        if "locator(" in locator and "body" not in locator:
            return f"{locator}.evaluate('el => el.scrollBy({{ top: el.clientHeight }})')"
        return "page.evaluate('() => window.scrollBy(0, window.innerHeight)')"
    if action == "scroll_to_text":
        return f"{locator}.scroll_into_view_if_needed()"
    if action == "open_tab":
        url = args.get("url", "")
        return f"page = context.new_page(); page.goto({url!r})"
    if action == "switch_tab":
        tab_id = int(args.get("tab_id", 0))
        return f"page = context.pages[{tab_id}]"
    if action == "close_tab":
        return "page.close()"
    if action == "get_dropdown_options":
        return f"# read-only: {locator}.locator('option').all_inner_texts()"
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
        elif entry.get("error"):
            skipped_failed += 1
    return skipped_failed, skipped_done
