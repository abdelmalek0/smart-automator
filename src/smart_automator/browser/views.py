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


@dataclass(frozen=True)
class ScrollRegion:
    """A discovered overflow region (window or element container)."""

    key: str
    kind: str  # "window" | "container"
    tag: str
    xpath: str
    scroll_top: int
    client_height: int
    scroll_height: int

    @property
    def overflow(self) -> int:
        return max(self.scroll_height - self.client_height, 0)

    @property
    def percent(self) -> int:
        overflow = self.overflow
        if overflow <= 0:
            return 0
        return max(0, min(100, round((self.scroll_top / overflow) * 100)))

    @property
    def at_top(self) -> bool:
        return self.scroll_top <= 2

    @property
    def at_bottom(self) -> bool:
        return self.scroll_top + self.client_height >= self.scroll_height - 2


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
    scroll_regions: list[ScrollRegion] = field(default_factory=list)

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
        scroll_regions: list[ScrollRegion] | None = None,
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
            scroll_regions=list(scroll_regions or []),
        )
