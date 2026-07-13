from __future__ import annotations

from dataclasses import dataclass, field

from .dom import DOMElementNode, DOMState


class URLNotAllowedError(Exception):
    pass


@dataclass
class TabInfo:
    id: int
    url: str
    title: str


@dataclass
class BrowserState:
    tab_id: int
    url: str
    title: str
    element_tree: DOMElementNode
    selector_map: dict[int, DOMElementNode]
    tabs: list[TabInfo] = field(default_factory=list)
    scroll_y: int = 0
    scroll_height: int = 0
    visual_viewport_height: int = 0
    screenshot: str | None = None

    @classmethod
    def from_dom_state(
        cls,
        dom_state: DOMState,
        tab_id: int,
        url: str,
        title: str,
        tabs: list[TabInfo],
        scroll_y: int,
        scroll_height: int,
        visual_viewport_height: int,
        screenshot: str | None = None,
    ) -> BrowserState:
        return cls(
            tab_id=tab_id,
            url=url,
            title=title,
            element_tree=dom_state.element_tree,
            selector_map=dom_state.selector_map,
            tabs=tabs,
            scroll_y=scroll_y,
            scroll_height=scroll_height,
            visual_viewport_height=visual_viewport_height,
            screenshot=screenshot,
        )
