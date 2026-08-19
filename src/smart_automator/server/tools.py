from __future__ import annotations

from ..actions.schemas import ACTION_NAMES

_ACTION_DOCS: dict[str, str] = {
    "done": "Mark the current task as complete.",
    "search_google": "Search Google for a query.",
    "go_to_url": "Navigate to a URL.",
    "go_back": "Go back in browser history.",
    "wait": "Wait for a number of seconds.",
    "click_element": "Click an indexed interactive element.",
    "input_text": "Type text into an indexed input element.",
    "switch_tab": "Switch to another browser tab by id.",
    "open_tab": "Open a new tab, optionally with a URL.",
    "close_tab": "Close a browser tab by id.",
    "cache_content": "Store page content in agent memory.",
    "scroll_to_percent": "Scroll the document or primary overflow region to a percentage on X and/or Y. Optional index selects a nearby scroll ancestor.",
    "scroll_to_top": "Scroll the document or primary overflow region to the top. Optional index selects a nearby scroll ancestor.",
    "scroll_to_bottom": "Scroll the document or primary overflow region to the bottom. Optional index selects a nearby scroll ancestor.",
    "previous_page": "Scroll up by one viewport in the document or primary overflow region. Optional index selects a nearby scroll ancestor.",
    "next_page": "Scroll down by one viewport in the document or primary overflow region. Optional index selects a nearby scroll ancestor.",
    "scroll_to_left": "Scroll the document or primary overflow region to the left edge. Optional index selects a nearby scroll ancestor.",
    "scroll_to_right": "Scroll the document or primary overflow region to the right edge. Optional index selects a nearby scroll ancestor.",
    "page_left": "Scroll left by one viewport in the document or primary overflow region. Optional index selects a nearby scroll ancestor.",
    "page_right": "Scroll right by one viewport in the document or primary overflow region. Optional index selects a nearby scroll ancestor.",
    "scroll_to_text": "Scroll until specific text is visible.",
    "send_keys": "Send keyboard keys to the page.",
    "get_dropdown_options": "Read options from a dropdown element.",
    "select_dropdown_option": "Select an option in a dropdown element.",
}

_ACTION_SIGNATURES: dict[str, str] = {
    "done": "(text?)",
    "search_google": "(query)",
    "go_to_url": "(url)",
    "go_back": "()",
    "wait": "(seconds)",
    "click_element": "(index, intent?)",
    "input_text": "(index, text, intent?)",
    "switch_tab": "(tab_id)",
    "open_tab": "(url?)",
    "close_tab": "(tab_id)",
    "cache_content": "(content)",
    "scroll_to_percent": "(index?, percent?, xPercent?)",
    "scroll_to_top": "(index?)",
    "scroll_to_bottom": "(index?)",
    "previous_page": "(index?)",
    "next_page": "(index?)",
    "scroll_to_left": "(index?)",
    "scroll_to_right": "(index?)",
    "page_left": "(index?)",
    "page_right": "(index?)",
    "scroll_to_text": "(text)",
    "send_keys": "(keys)",
    "get_dropdown_options": "(index)",
    "select_dropdown_option": "(index, option)",
}


def list_action_tools() -> list[dict[str, str]]:
    tools: list[dict[str, str]] = []
    for name in ACTION_NAMES:
        tools.append(
            {
                "name": name,
                "doc": _ACTION_DOCS.get(name, ""),
                "signature": _ACTION_SIGNATURES.get(name, "()"),
            }
        )
    return tools
