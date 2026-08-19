from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    name: str
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def intent(self) -> str | None:
        return self.args.get("intent")

    @property
    def index(self) -> int | None:
        value = self.args.get("index")
        return int(value) if value is not None else None

    def has_index(self) -> bool:
        return self.name in (
            "click_element",
            "input_text",
            "get_dropdown_options",
            "select_dropdown_option",
            "scroll_to_percent",
            "scroll_to_top",
            "scroll_to_bottom",
            "previous_page",
            "next_page",
            "scroll_to_left",
            "scroll_to_right",
            "page_left",
            "page_right",
        ) and self.index is not None


ACTION_NAMES = [
    "done",
    "search_google",
    "go_to_url",
    "go_back",
    "wait",
    "click_element",
    "input_text",
    "switch_tab",
    "open_tab",
    "close_tab",
    "cache_content",
    "scroll_to_percent",
    "scroll_to_top",
    "scroll_to_bottom",
    "previous_page",
    "next_page",
    "scroll_to_left",
    "scroll_to_right",
    "page_left",
    "page_right",
    "scroll_to_text",
    "send_keys",
    "get_dropdown_options",
    "select_dropdown_option",
]
