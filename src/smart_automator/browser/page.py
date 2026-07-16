from __future__ import annotations

import platform
import time
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


_RELEVANT_RESOURCE_TYPES = frozenset({"document", "stylesheet", "image", "font", "script", "iframe"})
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
        home_page_url: str = "https://www.google.com",
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
        self._last_highlight_signature: tuple[str, str, frozenset[str]] | None = None
        self._defer_post_action_stable = False
        self._ensure_script_injection()

    def set_defer_post_action_stable(self, defer: bool) -> None:
        """When True, interaction handlers skip their stable wait; batch settle handles it."""
        self._defer_post_action_stable = defer

    def _maybe_wait_after_interaction(self) -> None:
        if not self._defer_post_action_stable:
            self.wait_for_page_stable()

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

    def wait_for_page_stable(self, minimum_wait: float | None = None) -> None:
        start = time.monotonic()
        self._wait_for_stable_network()
        elapsed = time.monotonic() - start
        min_wait = minimum_wait if minimum_wait is not None else self._minimum_wait_page_load_time
        remaining = max(min_wait - elapsed, 0.0)
        if remaining > 0:
            time.sleep(remaining)

    def _wait_for_stable_network(self) -> None:
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
                time.sleep(0.1)
                idle_for = time.monotonic() - last_activity
                if not pending_requests and idle_for >= self._wait_for_network_idle_page_load_time:
                    break
                if time.monotonic() - start >= self._maximum_wait_page_load_time:
                    break
        finally:
            self._page.remove_listener("request", _track_request)
            self._page.remove_listener("response", _track_response)

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

    def get_dom_state(
        self,
        show_highlights: bool = True,
        *,
        wait_for_stable: bool = False,
        focus_element: int = -1,
    ) -> DOMState:
        if wait_for_stable:
            self.wait_for_page_stable()

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
        info = self._page.evaluate("""() => ({
            scrollY: window.scrollY,
            viewportHeight: window.visualViewport?.height || window.innerHeight,
            scrollHeight: Math.max(
                document.documentElement?.scrollHeight ?? 0,
                document.body?.scrollHeight ?? 0,
            ),
        })""")
        return int(info["scrollY"]), int(info["viewportHeight"]), int(info["scrollHeight"])

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
        handle = self._locate_element(element)
        if not handle:
            raise ValueError(f"Element not found: {element.highlight_index}")
        self._scroll_into_view_if_needed(handle)
        try:
            handle.click(timeout=2000)
            self._maybe_wait_after_interaction()
            self._check_and_handle_navigation()
        except URLNotAllowedError:
            raise
        except Exception:
            handle.evaluate("el => el.click()")
            self._maybe_wait_after_interaction()
            self._check_and_handle_navigation()
        self._cached_state = None

    def input_text(self, element: DOMElementNode, text: str):
        handle = self._locate_element(element)
        if not handle:
            raise ValueError(f"Element not found: {element.highlight_index}")
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
            handle.type(text, delay=50)
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

    def _locate_element(self, element: DOMElementNode) -> ElementHandle | None:
        current_frame: PlaywrightPage | Frame = self._page

        parents: list[DOMElementNode] = []
        current: DOMElementNode | None = element
        while current and current.parent:
            parents.append(current.parent)
            current = current.parent

        iframes = [parent for parent in reversed(parents) if parent.tag_name == "iframe"]
        for parent in iframes:
            frame_handle = self._query_unique_handle(current_frame, parent)
            if frame_handle is None:
                return None
            frame = frame_handle.content_frame()
            if not frame:
                return None
            current_frame = frame

        return self._query_unique_handle(current_frame, element)

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

    def _query_unique_handle(
        self,
        frame: PlaywrightPage | Frame,
        element: DOMElementNode,
    ) -> ElementHandle | None:
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
