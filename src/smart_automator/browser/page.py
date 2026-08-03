from __future__ import annotations

import platform
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Frame, Page as PlaywrightPage, ElementHandle, Request, Response

from .dom import (
    BUILD_DOM_TREE_SCRIPT_PATH,
    DOMElementNode,
    DOMState,
    HIGHLIGHT_CONTAINER_ID,
    build_dom_tree,
    calc_branch_path_hash_set,
    inject_build_dom_tree_script,
    remove_highlights,
)
from .history import is_file_uploader
from .util import is_url_allowed
from .views import URLNotAllowedError


_RELEVANT_RESOURCE_TYPES = frozenset({
    "document", "stylesheet", "image", "font", "script", "iframe", "xhr", "fetch",
})
_RELEVANT_CONTENT_TYPES = frozenset({
    "text/html", "text/css", "application/javascript", "image/", "font/", "application/json",
})
_IGNORED_URL_PATTERNS = (
    "analytics", "tracking", "telemetry", "beacon", "metrics",
    "doubleclick", "adsystem", "adserver", "advertising",
    "livechat", "zendesk", "intercom", "crisp.chat", "hotjar",
    "push-notifications", "onesignal", "pushwoosh",
    "heartbeat", "ping", "alive", "webrtc", "rtmp://", "wss://",
    "cloudfront.net", "fastly.net",
)

_ANTI_DETECTION_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : originalQuery(parameters)
);
(function () {
  const originalAttachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function attachShadow(options) {
    return originalAttachShadow.call(this, { ...options, mode: "open" });
  };
})();
"""

_EXECUTION_CONTEXT_DESTROYED_MARKERS = (
    "execution context was destroyed",
    "frame was detached",
    "target closed",
)

_SCROLL_INFO_JS = """() => ({
    scrollY: window.scrollY,
    viewportHeight: window.visualViewport?.height || window.innerHeight,
    scrollHeight: Math.max(
        document.documentElement?.scrollHeight ?? 0,
        document.body?.scrollHeight ?? 0,
    ),
})"""


def _is_destroyed_context_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _EXECUTION_CONTEXT_DESTROYED_MARKERS)


def _evaluate_resilient(
    evaluate_fn: Callable[..., object],
    *args: object,
    settle: Callable[[], None] | None = None,
    max_attempts: int = 3,
    swallow_destroyed: bool = False,
    **kwargs: object,
) -> object | None:
    """Retry evaluate calls that fail because navigation destroyed the JS context."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return evaluate_fn(*args, **kwargs)
        except Exception as exc:
            if not _is_destroyed_context_error(exc):
                raise
            last_exc = exc
            if attempt < max_attempts - 1:
                if settle is not None:
                    settle()
                continue
            if swallow_destroyed:
                return None
            raise
    if swallow_destroyed:
        return None
    if last_exc is not None:
        raise last_exc
    return None


_DOM_STABILITY_PROBE_JS = """
() => {
  const interactiveSelector = (
    'a, button, input, select, textarea, [role="button"], [role="link"], '
    + '[role="textbox"], [tabindex], flt-semantics[role]'
  );
  let interactive = 0;
  for (const el of document.querySelectorAll(interactiveSelector)) {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
      continue;
    }
    interactive += 1;
  }
  const text = document.body && document.body.innerText
    ? document.body.innerText.replace(/\\s+/g, ' ').trim()
    : '';
  return JSON.stringify({
    interactive,
    textLen: text.length,
    textSample: text.slice(0, 200),
  });
}
"""


class Page:
    def __init__(
        self,
        playwright_page: PlaywrightPage,
        page_id: int,
        *,
        minimum_wait_page_load_time: float = 0.25,
        wait_for_network_idle_page_load_time: float = 0.5,
        maximum_wait_page_load_time: float = 5.0,
        include_dynamic_attributes: bool = True,
        viewport_expansion: int = 0,
        allowed_urls: list[str] | None = None,
        denied_urls: list[str] | None = None,
        home_page_url: str = "about:blank",
        remote_cdp: bool = False,
    ):
        self._page = playwright_page
        self.page_id = page_id
        self._selector_map: dict[int, DOMElementNode] = {}
        self._cached_state: DOMState | None = None
        self._minimum_wait_page_load_time = minimum_wait_page_load_time
        self._wait_for_network_idle_page_load_time = wait_for_network_idle_page_load_time
        self._maximum_wait_page_load_time = maximum_wait_page_load_time
        self._include_dynamic_attributes = include_dynamic_attributes
        self._viewport_expansion = viewport_expansion
        self._allowed_urls = allowed_urls or []
        self._denied_urls = denied_urls or []
        self._home_page_url = home_page_url
        self._remote_cdp = remote_cdp
        self._last_highlight_signature: tuple[str, str, frozenset[str]] | None = None
        self._defer_post_action_stable = False
        self._ensure_script_injection()

    def set_defer_post_action_stable(self, defer: bool) -> None:
        """When True, interaction handlers skip their stable wait; batch settle handles it."""
        self._defer_post_action_stable = defer

    @property
    def defer_post_action_stable(self) -> bool:
        return self._defer_post_action_stable

    def _maybe_wait_after_interaction(self) -> None:
        if not self._defer_post_action_stable:
            self.wait_for_page_stable()

    def _settle_after_navigation_race(self) -> None:
        self.wait_for_page_stable(minimum_wait=0.1)

    def _evaluate_on_page(self, script: str, *args: object) -> object:
        return _evaluate_resilient(
            self._page.evaluate,
            script,
            *args,
            settle=self._settle_after_navigation_race,
        )

    def _evaluate_on_handle(
        self,
        handle: ElementHandle,
        script: str,
        *args: object,
        swallow_destroyed: bool = False,
    ) -> object | None:
        return _evaluate_resilient(
            handle.evaluate,
            script,
            *args,
            settle=self._settle_after_navigation_race,
            swallow_destroyed=swallow_destroyed,
        )

    def _ensure_script_injection(self) -> None:
        script_path = str(BUILD_DOM_TREE_SCRIPT_PATH)
        try:
            self._page.add_init_script(path=script_path)
            self._page.add_init_script(_ANTI_DETECTION_SCRIPT)
        except Exception:
            pass
        inject_build_dom_tree_script(self._page)

    @property
    def playwright_page(self) -> PlaywrightPage:
        return self._page

    def wait_for_page_stable(
        self,
        minimum_wait: float | None = None,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> bool:
        """Wait for page stability. Returns True if aborted early."""
        start = time.monotonic()
        if self._wait_for_stable_network(should_abort=should_abort):
            return True
        if self._wait_for_dom_stable(should_abort=should_abort):
            return True
        elapsed = time.monotonic() - start
        min_wait = minimum_wait if minimum_wait is not None else self._minimum_wait_page_load_time
        remaining = max(min_wait - elapsed, 0.0)
        if remaining > 0 and self._sleep_interruptible(remaining, should_abort=should_abort):
            return True
        return False

    def _probe_dom_signature(self) -> str:
        try:
            result = self._evaluate_on_page(_DOM_STABILITY_PROBE_JS)
            return str(result)
        except Exception:
            return ""

    def _sleep_interruptible(
        self,
        duration: float,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> bool:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if should_abort and should_abort():
                return True
            time.sleep(min(0.1, deadline - time.monotonic()))
        return False

    def _wait_for_dom_stable(
        self,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> bool:
        start = time.monotonic()
        last_signature: str | None = None
        last_change = time.monotonic()

        while time.monotonic() - start < self._maximum_wait_page_load_time:
            if should_abort and should_abort():
                return True
            signature = self._probe_dom_signature()
            if signature != last_signature:
                last_signature = signature
                last_change = time.monotonic()
            elif time.monotonic() - last_change >= self._wait_for_network_idle_page_load_time:
                return False
            if self._sleep_interruptible(0.1, should_abort=should_abort):
                return True
        return False

    def _wait_for_stable_network(
        self,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> bool:
        pending_requests: set[Request] = set()
        last_activity = time.monotonic()

        def _track_request(request: Request) -> None:
            nonlocal last_activity
            if request.resource_type not in _RELEVANT_RESOURCE_TYPES:
                return
            if request.resource_type in {"websocket", "media", "eventsource", "manifest", "other"}:
                return
            url = request.url.lower()
            if url.startswith("data:") or url.startswith("blob:"):
                return
            if any(pattern in url for pattern in _IGNORED_URL_PATTERNS):
                return
            headers = request.headers
            if headers.get("purpose") == "prefetch" or headers.get("sec-fetch-dest") in {"video", "audio"}:
                return
            pending_requests.add(request)
            last_activity = time.monotonic()

        def _track_response(response: Response) -> None:
            nonlocal last_activity
            request = response.request
            if request not in pending_requests:
                return
            content_type = (response.headers.get("content-type") or "").lower()
            if any(token in content_type for token in ("streaming", "video", "audio", "webm", "mp4", "event-stream", "websocket", "protobuf")):
                pending_requests.discard(request)
                return
            if not any(ct in content_type for ct in _RELEVANT_CONTENT_TYPES):
                pending_requests.discard(request)
                return
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > 5 * 1024 * 1024:
                pending_requests.discard(request)
                return
            pending_requests.discard(request)
            last_activity = time.monotonic()

        self._page.on("request", _track_request)
        self._page.on("response", _track_response)
        try:
            start = time.monotonic()
            while True:
                if should_abort and should_abort():
                    return True
                if self._sleep_interruptible(0.1, should_abort=should_abort):
                    return True
                idle_for = time.monotonic() - last_activity
                if not pending_requests and idle_for >= self._wait_for_network_idle_page_load_time:
                    break
                if time.monotonic() - start >= self._maximum_wait_page_load_time:
                    break
        finally:
            self._page.remove_listener("request", _track_request)
            self._page.remove_listener("response", _track_response)
        return False

    def _check_and_handle_navigation(self) -> None:
        current_url = self._page.url
        if is_url_allowed(current_url, self._allowed_urls, self._denied_urls):
            return
        error_message = f"URL: {current_url} is not allowed"
        safe_url = self._home_page_url or "about:blank"
        try:
            self._page.goto(safe_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        raise URLNotAllowedError(error_message)

    def goto(self, url: str):
        remove_highlights(self._page)
        self._clear_highlight_signature()
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        inject_build_dom_tree_script(self._page)
        self.wait_for_page_stable()
        self._check_and_handle_navigation()
        self._cached_state = None

    def url(self) -> str:
        return self._page.url

    def title(self) -> str:
        return self._page.title()

    def _highlights_visible(self) -> bool:
        try:
            return bool(
                self._page.main_frame.evaluate(
                    f"() => !!document.getElementById('{HIGHLIGHT_CONTAINER_ID}')"
                )
            )
        except Exception:
            return False

    def _page_signature(self, dom_state: DOMState) -> tuple[str, str, frozenset[str]]:
        return (
            self.url(),
            self.title(),
            frozenset(calc_branch_path_hash_set(dom_state)),
        )

    def _can_skip_highlight_redraw(
        self,
        last_signature: tuple[str, str, frozenset[str]],
        new_signature: tuple[str, str, frozenset[str]],
    ) -> bool:
        if last_signature[0] != new_signature[0] or last_signature[1] != new_signature[1]:
            return False
        return last_signature[2] == new_signature[2]

    def _clear_highlight_signature(self) -> None:
        self._last_highlight_signature = None

    def _minimal_dom_state(self) -> DOMState:
        root = DOMElementNode(tag_name="body", xpath="/html/body")
        return DOMState(element_tree=root, selector_map={})

    def get_dom_state(
        self,
        show_highlights: bool = True,
        *,
        wait_for_stable: bool = False,
        focus_element: int = -1,
        should_abort: Callable[[], bool] | None = None,
    ) -> DOMState:
        if should_abort and should_abort():
            return self._minimal_dom_state()

        if wait_for_stable:
            self.wait_for_page_stable(should_abort=should_abort)
            if should_abort and should_abort():
                return self._minimal_dom_state()

        # Over Connect/WSS CDP, avoid a second full build_dom_tree round-trip when
        # highlights are required — one payload is already expensive.
        if show_highlights and self._remote_cdp:
            if (
                self._highlights_visible()
                and self._last_highlight_signature is not None
            ):
                state_probe = build_dom_tree(
                    self._page,
                    show_highlights=True,
                    focus_element=focus_element,
                    viewport_expansion=self._viewport_expansion,
                    do_highlight_elements=False,
                )
                signature = self._page_signature(state_probe)
                if self._can_skip_highlight_redraw(self._last_highlight_signature, signature):
                    self._selector_map = state_probe.selector_map
                    self._cached_state = state_probe
                    return state_probe
                remove_highlights(self._page)
            state = build_dom_tree(
                self._page,
                show_highlights=True,
                focus_element=focus_element,
                viewport_expansion=self._viewport_expansion,
                do_highlight_elements=True,
            )
            self._last_highlight_signature = self._page_signature(state)
            self._selector_map = state.selector_map
            self._cached_state = state
            return state

        state_probe = build_dom_tree(
            self._page,
            show_highlights=show_highlights,
            focus_element=focus_element,
            viewport_expansion=self._viewport_expansion,
            do_highlight_elements=False,
        )
        signature = self._page_signature(state_probe)

        if (
            show_highlights
            and self._highlights_visible()
            and self._last_highlight_signature is not None
            and self._can_skip_highlight_redraw(self._last_highlight_signature, signature)
        ):
            self._selector_map = state_probe.selector_map
            self._cached_state = state_probe
            return state_probe

        if show_highlights:
            remove_highlights(self._page)
            state = build_dom_tree(
                self._page,
                show_highlights=show_highlights,
                focus_element=focus_element,
                viewport_expansion=self._viewport_expansion,
                do_highlight_elements=True,
            )
            self._last_highlight_signature = self._page_signature(state)
        else:
            state = state_probe

        self._selector_map = state.selector_map
        self._cached_state = state
        return state

    def get_cached_state(self) -> DOMState | None:
        return self._cached_state

    def get_scroll_info(self) -> tuple[int, int, int]:
        info = self._evaluate_on_page(_SCROLL_INFO_JS)
        if not isinstance(info, dict):
            raise TypeError(f"Expected scroll info dict, got {type(info)!r}")
        return (
            int(info["scrollY"]),
            int(info["viewportHeight"]),
            int(info["scrollHeight"]),
        )

    def probe_element_state(
        self,
        element: DOMElementNode,
        *,
        expected_value: str | None = None,
        expected_selected_text: str | None = None,
    ) -> dict | None:
        handle = self._locate_element(element)
        if not handle:
            return {"exists": False}
        try:
            return handle.evaluate(
                """(el, expectedValue, expectedSelectedText) => {
                    const tag = (el.tagName || '').toLowerCase();
                    const style = window.getComputedStyle(el);
                    const visible = !!(
                        (el.offsetWidth || el.offsetHeight) &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none'
                    );
                    let value = '';
                    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                        value = el.value || '';
                    } else if (el.isContentEditable) {
                        value = el.textContent || '';
                    }
                    let selectedText = '';
                    if (el.tagName === 'SELECT' && el.selectedIndex >= 0) {
                        selectedText = el.options[el.selectedIndex]?.text || '';
                    }
                    const result = {
                        exists: true,
                        tagName: tag,
                        valueLength: value.length,
                        disabled: !!(el.disabled || el.readOnly),
                        visible,
                        focused: document.activeElement === el,
                        checked: typeof el.checked === 'boolean' ? el.checked : null,
                        ariaChecked: el.getAttribute('aria-checked'),
                        ariaExpanded: el.getAttribute('aria-expanded'),
                        selectedIndex: el.tagName === 'SELECT' ? el.selectedIndex : null,
                        selectedTextLength: selectedText.length,
                    };
                    if (expectedValue !== null && expectedValue !== undefined) {
                        result.valueMatches = value === expectedValue;
                    }
                    if (expectedSelectedText !== null && expectedSelectedText !== undefined) {
                        result.selectedMatches = selectedText.trim() === String(expectedSelectedText).trim();
                    }
                    return result;
                }""",
                expected_value,
                expected_selected_text,
            )
        except Exception:
            return {"exists": False}

    def capture_snapshot(self, tab_ids: set[int]) -> PageSnapshot:
        from ..agent.verification import PageSnapshot
        from .dom import build_dom_tree, calc_branch_path_hash_set

        scroll_y, _, _ = self.get_scroll_info()
        dom = build_dom_tree(
            self._page,
            show_highlights=False,
            viewport_expansion=self._viewport_expansion,
        )
        signature = hash(frozenset(calc_branch_path_hash_set(dom)))
        return PageSnapshot(
            url=self.url(),
            title=self.title(),
            scroll_y=scroll_y,
            tab_ids=tuple(sorted(tab_ids)),
            dom_signature=signature,
            interactive_count=len(dom.selector_map),
        )

    def _find_nearest_scrollable_element(self, handle: ElementHandle) -> ElementHandle | None:
        is_scrollable = handle.evaluate(
            """el => {
                if (!(el instanceof HTMLElement)) return false;
                const style = window.getComputedStyle(el);
                const hasVerticalScrollbar = el.scrollHeight > el.clientHeight;
                const canScrollVertically =
                    style.overflowY === 'scroll' ||
                    style.overflowY === 'auto' ||
                    style.overflow === 'scroll' ||
                    style.overflow === 'auto';
                return hasVerticalScrollbar && canScrollVertically;
            }"""
        )
        if is_scrollable:
            return handle

        parent_handle = handle.evaluate_handle("el => el.parentElement")
        depth = 0
        while parent_handle and depth < 20:
            parent = parent_handle.as_element()
            if parent is None:
                break
            if parent.evaluate(
                """el => {
                    if (!(el instanceof HTMLElement)) return false;
                    const style = window.getComputedStyle(el);
                    const hasVerticalScrollbar = el.scrollHeight > el.clientHeight;
                    const canScrollVertically =
                        style.overflowY === 'scroll' ||
                        style.overflowY === 'auto' ||
                        style.overflow === 'scroll' ||
                        style.overflow === 'auto';
                    return hasVerticalScrollbar && canScrollVertically;
                }"""
            ):
                return parent
            parent_handle = parent.evaluate_handle("el => el.parentElement")
            depth += 1
        return handle

    def get_element_scroll_info(self, element: DOMElementNode) -> tuple[int, int, int]:
        handle = self._locate_element(element)
        if not handle:
            return 0, 0, 0
        scrollable = self._find_nearest_scrollable_element(handle)
        if not scrollable:
            return 0, 0, 0
        info = scrollable.evaluate("""el => ({
            scrollTop: el.scrollTop,
            clientHeight: el.clientHeight,
            scrollHeight: el.scrollHeight,
        })""")
        return int(info["scrollTop"]), int(info["clientHeight"]), int(info["scrollHeight"])

    def _wait_for_element_stability(self, handle: ElementHandle, timeout: float = 1.0) -> None:
        start = time.monotonic()
        last_rect = handle.bounding_box()
        while time.monotonic() - start < timeout:
            time.sleep(0.05)
            current_rect = handle.bounding_box()
            if not current_rect:
                break
            if (
                last_rect
                and abs(last_rect["x"] - current_rect["x"]) < 2
                and abs(last_rect["y"] - current_rect["y"]) < 2
                and abs(last_rect["width"] - current_rect["width"]) < 2
                and abs(last_rect["height"] - current_rect["height"]) < 2
            ):
                time.sleep(0.05)
                return
            last_rect = current_rect

    def _scroll_into_view_if_needed(self, handle: ElementHandle, timeout: float = 1.0) -> None:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            is_visible = handle.evaluate(
                """el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return false;
                    const style = window.getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
                        return false;
                    }
                    const inViewport =
                        rect.top >= 0 &&
                        rect.left >= 0 &&
                        rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                        rect.right <= (window.innerWidth || document.documentElement.clientWidth);
                    if (!inViewport) {
                        el.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'center' });
                        return false;
                    }
                    return true;
                }"""
            )
            if is_visible:
                return
            time.sleep(0.1)

    def click_element(self, element: DOMElementNode):
        if is_file_uploader(element):
            raise ValueError(
                f"Element {element.highlight_index} is a file uploader; cannot click directly"
            )
        handle = self._locate_element_with_retry(element)
        if not handle:
            raise ValueError(self._format_element_not_found_error(element))
        self._scroll_into_view_if_needed(handle)
        try:
            handle.click(timeout=2000)
            self._maybe_wait_after_interaction()
            self._check_and_handle_navigation()
        except URLNotAllowedError:
            raise
        except Exception:
            self._evaluate_on_handle(handle, "el => el.click()", swallow_destroyed=True)
            self._maybe_wait_after_interaction()
            self._check_and_handle_navigation()
        self._cached_state = None

    def input_text(self, element: DOMElementNode, text: str):
        handle = self._locate_element_with_retry(element)
        if not handle:
            raise ValueError(self._format_element_not_found_error(element))
        try:
            self._wait_for_element_stability(handle, 1.5)
            if not handle.is_hidden():
                self._scroll_into_view_if_needed(handle, 1.5)
        except Exception:
            pass

        props = handle.evaluate(
            """el => ({
                tagName: el.tagName.toLowerCase(),
                isContentEditable: el instanceof HTMLElement ? el.isContentEditable : false,
                isReadOnly: (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) ? el.readOnly : false,
                isDisabled: (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) ? el.disabled : false,
            })"""
        )
        tag_name = props["tagName"]
        is_content_editable = props["isContentEditable"]
        is_read_only = props["isReadOnly"]
        is_disabled = props["isDisabled"]

        if (is_content_editable or tag_name == "input") and not is_read_only and not is_disabled:
            handle.evaluate(
                """el => {
                    if (el instanceof HTMLElement) el.textContent = '';
                    if ('value' in el) el.value = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }"""
            )
            handle.type(text, delay=0 if self._remote_cdp else 50)
        else:
            handle.evaluate(
                """(el, value) => {
                    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                        el.value = value;
                    } else if (el instanceof HTMLElement && el.isContentEditable) {
                        el.textContent = value;
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                text,
            )
        self._maybe_wait_after_interaction()
        self._cached_state = None

    def send_keys(self, keys: str):
        key_map = {
            "enter": "Enter", "backspace": "Backspace", "tab": "Tab",
            "escape": "Escape", "space": " ", "arrowleft": "ArrowLeft",
            "arrowright": "ArrowRight", "arrowup": "ArrowUp", "arrowdown": "ArrowDown",
            "pagedown": "PageDown", "pageup": "PageUp", "delete": "Delete", "insert": "Insert",
            "meta": "Meta", "control": "Control", "ctrl": "Control", "shift": "Shift", "alt": "Alt",
        }
        is_mac = platform.system() == "Darwin"
        parts = keys.split("+")
        modifiers = parts[:-1]
        main_key = parts[-1]
        if is_mac:
            modifiers = ["meta" if part.lower() in {"ctrl", "control"} else part for part in modifiers]
        for part in modifiers:
            self._page.keyboard.down(key_map.get(part.lower(), part))
        self._page.keyboard.press(key_map.get(main_key.lower(), main_key))
        for part in reversed(modifiers):
            self._page.keyboard.up(key_map.get(part.lower(), part))
        self._maybe_wait_after_interaction()
        self._cached_state = None

    def _scroll_element(self, handle: ElementHandle, js: str):
        scrollable = self._find_nearest_scrollable_element(handle)
        if scrollable:
            scrollable.evaluate(js)

    def scroll_to_percent(self, percent: int, element: DOMElementNode | None = None):
        if element:
            handle = self._locate_element(element)
            if handle:
                self._scroll_element(
                    handle,
                    f"el => {{ el.scrollTo({{ top: (el.scrollHeight - el.clientHeight) * {percent} / 100, behavior: 'smooth' }}); }}",
                )
        else:
            self._page.evaluate(
                f"""() => {{
                    const h = Math.max(
                        document.documentElement.scrollHeight,
                        document.body.scrollHeight
                    ) - (window.visualViewport?.height || window.innerHeight);
                    window.scrollTo({{ top: h * {percent} / 100, behavior: 'smooth' }});
                }}"""
            )
        self._cached_state = None

    def scroll_to_previous_page(self, element: DOMElementNode | None = None):
        if element:
            handle = self._locate_element(element)
            if handle:
                self._scroll_element(
                    handle,
                    "el => { el.scrollBy({ top: -el.clientHeight, behavior: 'smooth' }); }",
                )
        else:
            self._page.evaluate(
                """() => {
                    const h = window.visualViewport?.height || window.innerHeight;
                    window.scrollBy({ top: -h, behavior: 'smooth' });
                }"""
            )
        self._cached_state = None

    def scroll_to_next_page(self, element: DOMElementNode | None = None):
        if element:
            handle = self._locate_element(element)
            if handle:
                self._scroll_element(
                    handle,
                    "el => { el.scrollBy({ top: el.clientHeight, behavior: 'smooth' }); }",
                )
        else:
            self._page.evaluate(
                """() => {
                    const h = window.visualViewport?.height || window.innerHeight;
                    window.scrollBy({ top: h, behavior: 'smooth' });
                }"""
            )
        self._cached_state = None

    def scroll_to_text(self, text: str, nth: int = 1) -> bool:
        found = self._page.evaluate(
            """([searchText, occurrence]) => {
                const lower = searchText.toLowerCase();
                const snapshot = document.evaluate(
                    `//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '${lower}')]`,
                    document,
                    null,
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                    null
                );
                let seen = 0;
                for (let i = 0; i < snapshot.snapshotLength; i++) {
                    const el = snapshot.snapshotItem(i);
                    if (!el) continue;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const visible =
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        style.opacity !== '0';
                    if (!visible) continue;
                    seen += 1;
                    if (seen === occurrence) {
                        el.scrollIntoView({ block: 'center' });
                        return true;
                    }
                }
                return false;
            }""",
            [text, nth],
        )
        if found:
            self._cached_state = None
        return bool(found)

    def get_dropdown_options(self, element: DOMElementNode) -> list[dict]:
        handle = self._locate_element(element)
        if not handle:
            return []
        return handle.evaluate("""select => {
            if (select.tagName !== 'SELECT') return [];
            return Array.from(select.options).map((opt, i) => ({
                index: i, text: opt.text, value: opt.value
            }));
        }""")

    def select_dropdown_option(self, element: DOMElementNode, text: str) -> str:
        handle = self._locate_element(element)
        if not handle:
            return "Element not found"
        result = handle.evaluate("""(select, optionText) => {
            if (select.tagName !== 'SELECT') return 'Not a select';
            const opt = Array.from(select.options).find(o => o.text.trim() === optionText);
            if (!opt) return 'Option not found';
            select.value = opt.value;
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return 'ok';
        }""", text)
        self._cached_state = None
        return result

    def go_back(self):
        remove_highlights(self._page)
        self._clear_highlight_signature()
        self._page.go_back()
        self.wait_for_page_stable()
        inject_build_dom_tree_script(self._page)
        self._check_and_handle_navigation()
        self._cached_state = None

    def take_screenshot(self) -> bytes:
        return self._page.screenshot(type="jpeg", quality=80)

    def save_screenshot_file(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=path, type="png", animations="disabled")

    def remove_highlight(self):
        remove_highlights(self._page)
        self._clear_highlight_signature()

    def _locate_element_with_retry(self, element: DOMElementNode) -> ElementHandle | None:
        handle = self._locate_element(element)
        if handle is not None:
            return handle
        time.sleep(0.15)
        self.wait_for_page_stable(minimum_wait=0.05)
        return self._locate_element(element)

    def _format_element_not_found_error(self, element: DOMElementNode) -> str:
        index = element.highlight_index
        index_part = str(index) if index is not None else "unknown"
        tag = element.tag_name or "unknown"
        xpath = element.xpath or "(none)"
        identity_bits: list[str] = []
        for attr in ("aria-label", "title", "placeholder", "name", "role"):
            value = element.attributes.get(attr, "").strip()
            if value:
                identity_bits.append(f"{attr}={value!r}")
        label = element.get_all_text_till_next_clickable_element().strip()
        if label:
            identity_bits.append(f"text={label!r}")
        identity = ", ".join(identity_bits) if identity_bits else "(no identity text)"
        shadow_note = " (inside shadow DOM)" if self._element_in_shadow_dom(element) else ""
        return (
            f"Element not found: index={index_part}, tag={tag}, xpath={xpath}, "
            f"{identity}{shadow_note}"
        )

    def _element_in_shadow_dom(self, element: DOMElementNode) -> bool:
        current: DOMElementNode | None = element
        while current and current.parent:
            if current.parent.shadow_root:
                return True
            current = current.parent
        return False

    def _locate_element(self, element: DOMElementNode) -> ElementHandle | None:
        boundaries: list[tuple[DOMElementNode, str]] = []
        node: DOMElementNode | None = element
        while node and node.parent:
            parent = node.parent
            if parent.tag_name == "iframe":
                boundaries.append((parent, "iframe"))
            elif parent.shadow_root:
                boundaries.append((parent, "shadow"))
            node = parent
        boundaries.reverse()

        frame: PlaywrightPage | Frame = self._page
        shadow_hosts: list[ElementHandle] = []

        for parent, kind in boundaries:
            host_handle = self._query_unique_handle(frame, parent, shadow_hosts)
            if host_handle is None:
                return None
            if kind == "iframe":
                content = host_handle.content_frame()
                if not content:
                    return None
                frame = content
                shadow_hosts = []
            else:
                shadow_hosts.append(host_handle)

        return self._query_unique_handle(frame, element, shadow_hosts)

    def _element_identity_text(self, element: DOMElementNode) -> str:
        text = element.get_all_text_till_next_clickable_element().strip().lower()
        if text:
            return text
        for attr in ("aria-label", "title", "placeholder", "value", "name"):
            value = element.attributes.get(attr, "").strip().lower()
            if value:
                return value
        return ""

    def _handle_matches_element(self, handle: ElementHandle, element: DOMElementNode) -> bool:
        expected = self._element_identity_text(element)
        if not expected:
            return True
        try:
            actual = handle.evaluate(
                """el => {
                    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                    const text = (el.innerText || el.textContent || '').trim();
                    const value = ('value' in el && el.value) ? String(el.value).trim() : '';
                    return (label || text || value || '').toLowerCase();
                }"""
            )
        except Exception:
            return True
        if not actual:
            return True
        return actual == expected or expected in actual or actual in expected

    def _query_in_shadow_root(
        self,
        host: ElementHandle,
        element: DOMElementNode,
    ) -> ElementHandle | None:
        xpath = element.xpath
        if xpath:
            try:
                full_xpath = xpath if xpath.startswith("/") else f"/{xpath}"
                js_handle = host.evaluate_handle(
                    """(hostEl, xpathExpr) => {
                        const root = hostEl.shadowRoot;
                        if (!root) return null;
                        const result = document.evaluate(
                            xpathExpr,
                            root,
                            null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE,
                            null,
                        );
                        return result.singleNodeValue;
                    }""",
                    full_xpath,
                )
                handle = js_handle.as_element()
                if handle and self._handle_matches_element(handle, element):
                    return handle
            except Exception:
                pass

        css_selector = element.enhanced_css_selector_for_element(self._include_dynamic_attributes)
        if css_selector:
            try:
                match_count = host.evaluate(
                    """(hostEl, selector) => {
                        const root = hostEl.shadowRoot;
                        return root ? root.querySelectorAll(selector).length : 0;
                    }""",
                    css_selector,
                )
                for index in range(int(match_count or 0)):
                    handle = host.evaluate_handle(
                        """(hostEl, selector, idx) => {
                            const root = hostEl.shadowRoot;
                            if (!root) return null;
                            const nodes = root.querySelectorAll(selector);
                            return nodes[idx] || null;
                        }""",
                        css_selector,
                        index,
                    ).as_element()
                    if handle and self._handle_matches_element(handle, element):
                        return handle
            except Exception:
                pass

        return None

    def _query_unique_handle(
        self,
        frame: PlaywrightPage | Frame,
        element: DOMElementNode,
        shadow_hosts: list[ElementHandle] | None = None,
    ) -> ElementHandle | None:
        if shadow_hosts:
            return self._query_in_shadow_root(shadow_hosts[-1], element)

        # Prefer xpath — CSS with shared classes often matches the wrong keypad/button.
        xpath = element.xpath
        if xpath:
            try:
                full_xpath = xpath if xpath.startswith("/") else f"/{xpath}"
                handle = frame.query_selector(f"xpath={full_xpath}")
                if handle and self._handle_matches_element(handle, element):
                    return handle
            except Exception:
                pass

        css_selector = element.enhanced_css_selector_for_element(self._include_dynamic_attributes)
        if css_selector:
            try:
                matches = frame.query_selector_all(css_selector)
            except Exception:
                matches = []
            if len(matches) == 1 and self._handle_matches_element(matches[0], element):
                return matches[0]
            if len(matches) > 1:
                for handle in matches:
                    if self._handle_matches_element(handle, element):
                        return handle

        return None
