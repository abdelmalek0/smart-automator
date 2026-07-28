from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import sync_playwright, Browser, BrowserContext as PlaywrightContext

from ..config import Config, resolve_chrome_user_data
from .chrome_profile_mirror import resolve_persistent_launch_dir
from .dom import DOMState, calc_branch_path_hash_set, mark_new_elements, remove_highlights
from .page import Page
from .util import is_url_allowed
from .views import BrowserState, TabInfo, URLNotAllowedError


class BrowserContext:
    def __init__(self, config: Config):
        self._config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: PlaywrightContext | None = None
        self._pages: dict[int, Page] = {}
        self._current_page_id: int | None = None
        self._next_page_id = 0
        self._previous_branch_hashes: set[str] | None = None

    def launch(self, *, cdp_url: str | None = None, fresh_profile: bool | None = None):
        effective_cdp = (cdp_url or self._config.cdp_url or "").strip()
        effective_fresh = (
            self._config.fresh_profile if fresh_profile is None else fresh_profile
        )

        self._playwright = sync_playwright().start()
        if effective_cdp:
            self._browser = self._playwright.chromium.connect_over_cdp(effective_cdp)
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = self._browser.new_context(
                    viewport={
                        "width": self._config.viewport_width,
                        "height": self._config.viewport_height,
                    },
                    color_scheme="light",
                )
            return

        launch_kwargs: dict = {"headless": self._config.headless}
        launch_args: list[str] = []
        if self._config.headless:
            launch_args.extend(
                [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
        else:
            launch_kwargs["channel"] = "chrome"

        profile_directory = (self._config.chrome_profile_directory or "").strip()

        user_data_dir = resolve_chrome_user_data(
            self._config.chrome_user_data,
            fresh_profile=effective_fresh,
        )
        if user_data_dir and not effective_fresh:
            launch_dir, launch_profile_dir = resolve_persistent_launch_dir(
                user_data_dir,
                profile_directory,
            )
            if launch_profile_dir:
                launch_args.append(f"--profile-directory={launch_profile_dir}")
            if launch_args:
                launch_kwargs["args"] = launch_args
            self._context = self._playwright.chromium.launch_persistent_context(
                launch_dir,
                **launch_kwargs,
                viewport={"width": self._config.viewport_width, "height": self._config.viewport_height},
                color_scheme="light",
            )
            self._browser = self._context.browser
            return

        if launch_args:
            launch_kwargs["args"] = launch_args

        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            viewport={"width": self._config.viewport_width, "height": self._config.viewport_height},
            color_scheme="light",
        )

    def _check_url(self, url: str):
        if not is_url_allowed(url, self._config.allowed_urls, self._config.denied_urls):
            raise URLNotAllowedError(f"URL not allowed: {url}")

    def new_page(self, url: str | None = None) -> int:
        if not self._context:
            raise RuntimeError("Browser not launched")
        playwright_page = self._context.new_page()
        page_id = self._next_page_id
        self._next_page_id += 1
        page = Page(
            playwright_page,
            page_id,
            minimum_wait_page_load_time=self._config.minimum_wait_page_load_time,
            wait_for_network_idle_page_load_time=self._config.wait_for_network_idle_page_load_time,
            maximum_wait_page_load_time=self._config.maximum_wait_page_load_time,
            include_dynamic_attributes=self._config.include_dynamic_attributes,
            viewport_expansion=self._config.viewport_expansion,
            allowed_urls=self._config.allowed_urls,
            denied_urls=self._config.denied_urls,
            home_page_url=self._config.home_page_url,
        )
        self._pages[page_id] = page
        self._current_page_id = page_id
        if url:
            self._check_url(url)
            page.goto(url)
        return page_id

    def get_current_page(self) -> Page:
        if self._current_page_id is None or self._current_page_id not in self._pages:
            raise RuntimeError("No page available")
        return self._pages[self._current_page_id]

    def get_page(self, page_id: int | None = None) -> Page:
        pid = page_id if page_id is not None else self._current_page_id
        if pid is None or pid not in self._pages:
            raise RuntimeError("No page available")
        return self._pages[pid]

    @property
    def current_page_id(self) -> int | None:
        return self._current_page_id

    def navigate_to(self, url: str):
        self._check_url(url)
        self.get_current_page().goto(url)

    def open_tab(self, url: str) -> Page:
        self._check_url(url)
        page_id = self.new_page(url)
        return self.get_page(page_id)

    def switch_tab(self, tab_id: int) -> Page:
        if tab_id not in self._pages:
            raise ValueError(f"Tab {tab_id} not found")
        self._current_page_id = tab_id
        return self._pages[tab_id]

    def close_tab(self, tab_id: int):
        if tab_id not in self._pages:
            raise ValueError(f"Tab {tab_id} not found")
        page = self._pages.pop(tab_id)
        try:
            page.playwright_page.close()
        except Exception:
            pass
        if self._current_page_id == tab_id:
            self._current_page_id = next(iter(self._pages), None)

    def get_tab_infos(self) -> list[TabInfo]:
        tabs: list[TabInfo] = []
        for page_id, page in self._pages.items():
            tabs.append(TabInfo(id=page_id, url=page.url(), title=page.title()))
        return tabs

    def get_all_tab_ids(self) -> set[int]:
        return set(self._pages.keys())

    def get_state(
        self,
        use_vision: bool = False,
        show_highlights: bool = True,
        *,
        wait_for_stable: bool = False,
        should_abort: Callable[[], bool] | None = None,
    ) -> BrowserState:
        page = self.get_current_page()
        dom_state = page.get_dom_state(
            show_highlights=show_highlights,
            wait_for_stable=wait_for_stable,
            should_abort=should_abort,
        )
        mark_new_elements(dom_state, self._previous_branch_hashes)
        self._previous_branch_hashes = calc_branch_path_hash_set(dom_state)
        scroll_y, viewport_h, scroll_h = page.get_scroll_info()
        screenshot = page.take_screenshot() if use_vision else None
        return BrowserState.from_dom_state(
            dom_state=dom_state,
            tab_id=page.page_id,
            url=page.url(),
            title=page.title(),
            tabs=self.get_tab_infos(),
            scroll_y=scroll_y,
            scroll_height=scroll_h,
            visual_viewport_height=viewport_h,
            screenshot=screenshot,
        )

    def get_cached_state(self) -> BrowserState:
        page = self.get_current_page()
        dom_state = page.get_cached_state()
        if dom_state is None:
            return self.get_state()
        scroll_y, viewport_h, scroll_h = page.get_scroll_info()
        return BrowserState.from_dom_state(
            dom_state=dom_state,
            tab_id=page.page_id,
            url=page.url(),
            title=page.title(),
            tabs=self.get_tab_infos(),
            scroll_y=scroll_y,
            scroll_height=scroll_h,
            visual_viewport_height=viewport_h,
        )

    def remove_highlight(self):
        for page in self._pages.values():
            page.remove_highlight()

    def close(self):
        for page in self._pages.values():
            try:
                page.playwright_page.close()
            except Exception:
                pass
        self._pages.clear()
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            self._playwright.stop()
