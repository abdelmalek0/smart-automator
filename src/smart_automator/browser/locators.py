"""Shared locator policy for live actions, history remap, and Playwright replay."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from playwright.sync_api import FrameLocator, Locator, Page as PlaywrightPage

TESTID_ATTRS = ("data-testid", "data-cy", "data-test", "data-qa")
IDENTITY_ATTRS = ("aria-label", "placeholder", "name", "title")
RADIO_CHECKBOX_TYPES = frozenset({"radio", "checkbox"})
EDITABLE_LEAF_SELECTOR = (
    'input, textarea, [contenteditable="true"], [role="textbox"]'
)
INTERACTIVE_LEAF_SELECTOR = (
    "button, a, input, select, textarea, "
    '[role="button"], [role="link"], [role="textbox"], [role="checkbox"], '
    '[role="radio"], [role="menuitem"], [role="tab"], [role="option"], '
    '[contenteditable="true"]'
)
IDENTITY_LOCATOR_KINDS = frozenset({
    "testid", "css", "role", "label", "placeholder", "text", "relative",
})
DEFAULT_RESOLVE_POLL_SECONDS = 15.0
DEFAULT_RESOLVE_POLL_INTERVAL = 0.2
ELEMENT_CLICK_TIMEOUT_MS = 5000
CENTER_SCROLL_JS = (
    "el => { if (el instanceof Element) el.scrollIntoView("
    "{ behavior: 'auto', block: 'center', inline: 'center' }); }"
)
JS_CLICK_JS = "el => el.click()"
_NON_RETRYABLE_CLICK_MARKERS = (
    "not attached",
    "element is not attached",
    "target closed",
    "target page, context or browser has been closed",
    "frame was detached",
    "frame has been detached",
)
_DESTROYED_CONTEXT_MARKERS = (
    "execution context was destroyed",
    "cannot find context with specified id",
    "frame was detached",
    "target closed",
)

_FLUTTER_ID_IN_CSS = re.compile(r'\[id="flt-semantic-node-\d+"\]')
_UNSTABLE_ID_IN_CSS = re.compile(
    r'\[id="(?:flt-semantic-node-\d+|mui-\d+|ember\d+|:r[\w-]+:|:R[\w-]+:)"\]'
)
_IDENTITY_ATTR_IN_CSS = re.compile(
    r'\[(?:aria-label|placeholder|name|title|data-testid|data-cy|data-test|data-qa)\s*=',
    re.IGNORECASE,
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HEX_HASH_RE = re.compile(r"^[a-f0-9]{8,}$", re.IGNORECASE)
_REACT_USE_ID_RE = re.compile(r"^:r[\w-]*:$", re.IGNORECASE)
_TAG_ROLES = {
    "button": "button",
    "a": "link",
    "select": "combobox",
    "textarea": "textbox",
    "summary": "button",
}
_INPUT_TYPE_ROLES = {
    "button": "button",
    "submit": "button",
    "reset": "button",
    "checkbox": "checkbox",
    "radio": "radio",
    "range": "slider",
    "file": "button",
}


class ReplayLocatorError(LookupError):
    """Raised when a replay step cannot uniquely resolve its target element."""


class ClickTarget(Protocol):
    def click(self, *, timeout: float = ...) -> None: ...
    def evaluate(self, expression: str, *args: Any) -> Any: ...


def is_non_retryable_click_error(exc: BaseException) -> bool:
    if type(exc).__name__ == "URLNotAllowedError":
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _NON_RETRYABLE_CLICK_MARKERS)


def _is_destroyed_context_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _DESTROYED_CONTEXT_MARKERS)


def click_with_fallback(
    target: ClickTarget,
    *,
    verify: Callable[[], None] | None = None,
    timeout_ms: int = ELEMENT_CLICK_TIMEOUT_MS,
) -> None:
    """Playwright-click a resolved node; JS-click only after an actionability miss.

    Does not re-resolve. On intercept/timeout, re-checks identity on the same
    node (when ``verify`` is provided) and only then dispatches ``el.click()``.
    """
    try:
        target.evaluate(CENTER_SCROLL_JS)
    except Exception:
        pass
    try:
        target.click(timeout=timeout_ms)
        return
    except Exception as exc:
        if is_non_retryable_click_error(exc):
            raise
        if verify is not None:
            try:
                verify()
            except Exception:
                raise exc from None
        try:
            target.evaluate(JS_CLICK_JS)
        except Exception as js_exc:
            if _is_destroyed_context_error(js_exc):
                return
            raise


def is_unstable_id(element_id: str | None) -> bool:
    if not element_id:
        return True
    value = element_id.strip()
    if not value:
        return True
    if value.startswith("flt-semantic-node-"):
        return True
    if value.startswith("mui-") and value[4:].isdigit():
        return True
    if value.startswith("ember") and value[5:].isdigit():
        return True
    if _REACT_USE_ID_RE.match(value):
        return True
    if _UUID_RE.match(value):
        return True
    if _HEX_HASH_RE.match(value):
        return True
    return False


def is_hashed_css_class(class_name: str) -> bool:
    name = class_name.strip()
    if not name:
        return True
    lowered = name.lower()
    if lowered.startswith(("css-", "sc-", "mui-")):
        return True
    if re.search(r"[a-f0-9]{6,}$", lowered) and re.search(r"\d", lowered):
        return True
    return False


def testid_from_attrs(attrs: dict[str, str]) -> tuple[str, str] | None:
    for key in TESTID_ATTRS:
        value = (attrs.get(key) or "").strip()
        if value:
            return key, value
    return None


def inferred_role(tag_name: str, attrs: dict[str, str]) -> str | None:
    explicit = (attrs.get("role") or "").strip().lower()
    if explicit and explicit not in {"presentation", "none", "generic"}:
        return explicit
    tag = (tag_name or "").strip().lower()
    if tag == "input":
        input_type = (attrs.get("type") or "text").strip().lower() or "text"
        return _INPUT_TYPE_ROLES.get(input_type, "textbox")
    return _TAG_ROLES.get(tag)


def css_id_selector(element_id: str) -> str:
    if re.fullmatch(r"[A-Za-z_][\w-]*", element_id):
        return f"#{element_id}"
    escaped = element_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'[id="{escaped}"]'


def normalize_xpath(xpath: str) -> str:
    xpath_target = xpath if xpath.startswith(("xpath=", "/")) else f"xpath=/{xpath.lstrip('/')}"
    if not xpath_target.startswith("xpath="):
        xpath_target = f"xpath={xpath_target}"
    return xpath_target


def sanitize_css_selector(css: str) -> str:
    cleaned = _UNSTABLE_ID_IN_CSS.sub("", css)
    return _FLUTTER_ID_IN_CSS.sub("", cleaned)


def css_has_identity_attrs(selector: str) -> bool:
    return bool(_IDENTITY_ATTR_IN_CSS.search(selector))


def _normalize_identity_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def identity_values_equal(expected: str, actual: str) -> bool:
    return _normalize_identity_text(expected) == _normalize_identity_text(actual)


def _element_mapping(element: dict[str, Any] | None) -> dict[str, Any]:
    return element if isinstance(element, dict) else {}


def element_attrs(element: dict[str, Any] | None) -> dict[str, str]:
    attrs = _element_mapping(element).get("attributes") or {}
    return {str(key): str(value) for key, value in attrs.items()}


def element_accessible_name(element: dict[str, Any] | None) -> str | None:
    raw = _element_mapping(element).get("accessibleName", _element_mapping(element).get("accessible_name"))
    if raw is None:
        return None
    name = str(raw).strip()
    return name or None


def element_tag_name(element: dict[str, Any] | None) -> str:
    mapping = _element_mapping(element)
    return str(mapping.get("tagName") or mapping.get("tag_name") or "").strip()


def element_frame_path(element: dict[str, Any] | None) -> list[str]:
    mapping = _element_mapping(element)
    raw = mapping.get("framePath") or mapping.get("frame_path") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def recorded_element_identity(step: dict[str, Any]) -> dict[str, str]:
    """Return distinguishing attributes recorded for a replay step's target."""
    element = step.get("element") if isinstance(step, dict) else None
    attrs = element_attrs(element)
    identity: dict[str, str] = {}
    input_type = (attrs.get("type") or "").strip().lower()
    for key in IDENTITY_ATTRS:
        value = (attrs.get(key) or "").strip()
        if not value:
            continue
        if key == "name" and input_type in RADIO_CHECKBOX_TYPES:
            continue
        identity[key] = value
    accessible = element_accessible_name(element)
    if accessible:
        identity.setdefault("accessibleName", accessible)
    testid = testid_from_attrs(attrs)
    if testid:
        identity.setdefault("testid", testid[1])
    element_id = (attrs.get("id") or "").strip()
    if element_id and not is_unstable_id(element_id):
        identity.setdefault("id", element_id)
    return identity


def step_has_recorded_identity(step: dict[str, Any]) -> bool:
    if recorded_element_identity(step):
        return True
    args = step.get("args") or {}
    css = args.get("css_selector")
    if css and css_has_identity_attrs(str(css)):
        return True
    if css and css_has_identity_attrs(sanitize_css_selector(str(css))):
        return True
    return False


def relative_xpath(ancestor_xpath: str, node_xpath: str) -> str | None:
    ancestor = (ancestor_xpath or "").strip().strip("/")
    node = (node_xpath or "").strip().strip("/")
    if not ancestor or not node:
        return None
    if node == ancestor:
        return "."
    prefix = ancestor + "/"
    if node.startswith(prefix):
        return "./" + node[len(prefix):]
    return None


def split_locator_candidates(
    step: dict[str, Any],
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
    args = step.get("args") or {}
    element = step.get("element") or {}
    attrs = element_attrs(element)
    identity: list[tuple[str, dict[str, Any]]] = []
    positional: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def _add(bucket: list[tuple[str, dict[str, Any]]], kind: str, params: dict[str, Any]) -> None:
        key = (kind, tuple(sorted((str(k), str(v)) for k, v in params.items())))
        if key in seen:
            return
        seen.add(key)
        bucket.append((kind, params))

    testid = testid_from_attrs(attrs)
    if testid:
        attr, value = testid
        _add(identity, "testid", {"attr": attr, "value": value})

    element_id = (attrs.get("id") or "").strip()
    if element_id and not is_unstable_id(element_id):
        _add(identity, "css", {"selector": css_id_selector(element_id)})

    accessible_name = element_accessible_name(element)
    role = inferred_role(element_tag_name(element), attrs)
    if role and accessible_name:
        _add(identity, "role", {"role": role, "name": accessible_name})

    if label := (attrs.get("aria-label") or "").strip():
        _add(identity, "label", {"label": label})
    if placeholder := (attrs.get("placeholder") or "").strip():
        _add(identity, "placeholder", {"placeholder": placeholder})

    input_type = (attrs.get("type") or "").strip().lower()
    name = (attrs.get("name") or "").strip()
    if name and input_type not in RADIO_CHECKBOX_TYPES:
        tag = element_tag_name(element) or "*"
        _add(identity, "css", {"selector": f'{tag}[name="{name}"]'})

    if accessible_name and len(accessible_name) <= 80:
        _add(identity, "text", {"text": accessible_name})

    stable_root = str(element.get("stableRoot") or element.get("stable_root") or "").strip()
    rel_xpath = str(element.get("relativeXPath") or element.get("relative_xpath") or "").strip()
    if stable_root and rel_xpath:
        _add(identity, "relative", {"root": stable_root, "xpath": rel_xpath})

    css = args.get("css_selector") or element.get("cssSelector") or element.get("css_selector")
    xpath = args.get("xpath") or element.get("xpath")

    def _add_css(selector: str) -> None:
        cleaned = sanitize_css_selector(selector)
        if not cleaned.strip():
            return
        entry_kind = "css"
        params = {"selector": cleaned}
        if css_has_identity_attrs(cleaned):
            _add(identity, entry_kind, params)
        else:
            _add(positional, entry_kind, params)

    if element_id and is_unstable_id(element_id) and css:
        _add_css(str(css))
    if css and not any(kind == "css" for kind, _ in identity + positional):
        _add_css(str(css))
    if xpath:
        _add(positional, "xpath", {"xpath": normalize_xpath(str(xpath))})
    if (text := args.get("text")) and step.get("action") == "scroll_to_text":
        _add(identity, "text", {"text": text})

    return identity, positional


def _scope_for_step(page: PlaywrightPage, step: dict[str, Any]) -> PlaywrightPage | FrameLocator:
    frames = element_frame_path(step.get("element"))
    scope: PlaywrightPage | FrameLocator = page
    for frame_selector in frames:
        selector = frame_selector
        if selector.startswith("/") or selector.startswith("xpath="):
            selector = normalize_xpath(selector)
        scope = scope.frame_locator(selector)
    return scope


def apply_locator(
    page: PlaywrightPage,
    kind: str,
    params: dict[str, Any],
    *,
    step: dict[str, Any] | None = None,
) -> Locator:
    scope = _scope_for_step(page, step or {})
    if kind == "testid":
        attr = params.get("attr") or "data-testid"
        value = params["value"]
        if attr == "data-testid" and hasattr(scope, "get_by_test_id"):
            return scope.get_by_test_id(value)
        return scope.locator(f'[{attr}="{value}"]')
    if kind == "label":
        return scope.get_by_label(params["label"], exact=True)
    if kind == "placeholder":
        return scope.get_by_placeholder(params["placeholder"], exact=True)
    if kind == "role":
        return scope.get_by_role(params["role"], name=params["name"], exact=True)
    if kind == "css":
        return scope.locator(params["selector"])
    if kind == "xpath":
        return scope.locator(params["xpath"])
    if kind == "text":
        return scope.get_by_text(params["text"], exact=True)
    if kind == "relative":
        return scope.locator(params["root"]).locator(f"xpath={params['xpath']}")
    return page.locator("body")


def _visible_locator(locator: Locator) -> Locator:
    try:
        return locator.filter(visible=True)
    except TypeError:
        return locator
    except Exception:
        return locator


def _count(locator: Locator) -> int | None:
    try:
        count = locator.count()
    except Exception:
        return None
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return count


def unique_locator_or_none(
    locator: Locator,
    *,
    leaf_selector: str | None = None,
) -> Locator | None:
    visible = _visible_locator(locator)
    count = _count(visible)
    if count is None:
        count = _count(locator)
        visible = locator
        if count is None:
            return None
    if count == 1:
        return visible
    if count > 1 and leaf_selector:
        leaf = visible.locator(leaf_selector)
        leaf_visible = _visible_locator(leaf)
        leaf_count = _count(leaf_visible)
        if leaf_count is None:
            leaf_count = _count(leaf)
            leaf_visible = leaf
        if leaf_count == 1:
            return leaf_visible
    return None


def _leaf_selector_for_action(action: str) -> str | None:
    if action == "input_text":
        return EDITABLE_LEAF_SELECTOR
    if action in {"click_element", "select_dropdown_option", "get_dropdown_options"}:
        return INTERACTIVE_LEAF_SELECTOR
    return None


def try_resolve_from_candidates(
    page: PlaywrightPage,
    candidates: list[tuple[str, dict[str, Any]]],
    *,
    step: dict[str, Any],
    leaf_selector: str | None,
) -> Locator | None:
    for kind, params in candidates:
        locator = apply_locator(page, kind, params, step=step)
        allow_leaf = leaf_selector if kind in IDENTITY_LOCATOR_KINDS else None
        unique = unique_locator_or_none(locator, leaf_selector=allow_leaf)
        if unique is not None:
            return unique
    return None


def resolve_replay_locator(
    page: PlaywrightPage,
    step: dict[str, Any],
    *,
    poll_timeout_seconds: float = DEFAULT_RESOLVE_POLL_SECONDS,
    poll_interval_seconds: float = DEFAULT_RESOLVE_POLL_INTERVAL,
) -> Locator:
    identity_candidates, positional_candidates = split_locator_candidates(step)
    has_identity = bool(identity_candidates) or step_has_recorded_identity(step)
    leaf_selector = _leaf_selector_for_action(str(step.get("action") or ""))

    if not identity_candidates and not positional_candidates:
        raise ReplayLocatorError("No locator candidates captured for replay step")

    deadline = time.monotonic() + max(0.0, poll_timeout_seconds)
    while True:
        if identity_candidates:
            resolved = try_resolve_from_candidates(
                page,
                identity_candidates,
                step=step,
                leaf_selector=leaf_selector,
            )
            if resolved is not None:
                return resolved
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.01, poll_interval_seconds))

    if has_identity:
        raise ReplayLocatorError(
            "Could not uniquely resolve element by recorded identity "
            "(refusing positional xpath/css fallback)"
        )

    resolved = try_resolve_from_candidates(
        page,
        positional_candidates,
        step=step,
        leaf_selector=None,
    )
    if resolved is not None:
        return resolved

    raise ReplayLocatorError("Could not uniquely resolve replay element locator")


def assert_locator_matches_identity(locator: Locator, step: dict[str, Any]) -> None:
    """Fail if the resolved node no longer matches recorded distinguishing attrs."""
    expected = recorded_element_identity(step)
    if not expected:
        return

    try:
        actual = locator.evaluate(
            """el => {
                const aria = (el.getAttribute('aria-label') || '').trim();
                const placeholder = (el.getAttribute('placeholder') || '').trim();
                const name = (el.getAttribute('name') || '').trim();
                const title = (el.getAttribute('title') || '').trim();
                const id = (el.getAttribute('id') || '').trim();
                const testid = (
                    el.getAttribute('data-testid')
                    || el.getAttribute('data-cy')
                    || el.getAttribute('data-test')
                    || el.getAttribute('data-qa')
                    || ''
                ).trim();
                const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                return { aria, placeholder, name, title, id, testid, text };
            }"""
        )
    except Exception as exc:
        raise ReplayLocatorError(
            f"Could not verify resolved element identity: {exc}"
        ) from exc

    attr_map = {
        "aria-label": "aria",
        "placeholder": "placeholder",
        "name": "name",
        "title": "title",
        "id": "id",
        "testid": "testid",
    }
    for key, expected_value in expected.items():
        if key == "accessibleName":
            aria = (actual.get("aria") or "").strip()
            title = (actual.get("title") or "").strip()
            text = (actual.get("text") or "").strip()
            if any(
                identity_values_equal(expected_value, candidate)
                for candidate in (aria, title, text)
            ):
                continue
            raise ReplayLocatorError(
                f"Resolved element accessible name does not match recorded "
                f"{expected_value!r} (aria={aria!r}, text={text!r})"
            )
        actual_key = attr_map.get(key)
        if not actual_key:
            continue
        got = (actual.get(actual_key) or "").strip()
        if not identity_values_equal(expected_value, got):
            raise ReplayLocatorError(
                f"Resolved element {key}={got!r} does not match recorded {expected_value!r}"
            )


def format_locator_expr(kind: str, params: dict[str, Any], *, root: str = "page") -> str:
    if kind == "testid":
        attr = params.get("attr") or "data-testid"
        value = params["value"]
        if attr == "data-testid":
            return f"{root}.get_by_test_id({value!r})"
        return f"{root}.locator({f'[{attr}=\"{value}\"]'!r})"
    if kind == "label":
        return f"{root}.get_by_label({params['label']!r}, exact=True)"
    if kind == "placeholder":
        return f"{root}.get_by_placeholder({params['placeholder']!r}, exact=True)"
    if kind == "role":
        return (
            f"{root}.get_by_role({params['role']!r}, name={params['name']!r}, exact=True)"
        )
    if kind == "css":
        return f"{root}.locator({params['selector']!r})"
    if kind == "xpath":
        return f"{root}.locator({normalize_xpath(params['xpath'])!r})"
    if kind == "text":
        return f"{root}.get_by_text({params['text']!r}, exact=True)"
    if kind == "relative":
        return (
            f"{root}.locator({params['root']!r}).locator("
            f"{('xpath=' + params['xpath'])!r})"
        )
    return f"{root}.locator('body')  # fallback — no stable locator captured"


def playwright_locator_expr(step: dict[str, Any]) -> str:
    identity, positional = split_locator_candidates(step)
    candidates = identity or positional
    if not candidates:
        return "page.locator('body')  # fallback — no stable locator captured"
    frames = element_frame_path(step.get("element"))
    root = "page"
    for frame_selector in frames:
        selector = frame_selector
        if selector.startswith("/") or selector.startswith("xpath="):
            selector = normalize_xpath(selector)
        root = f"{root}.frame_locator({selector!r})"
    kind, params = candidates[0]
    return format_locator_expr(kind, params, root=root)


RESOLVE_UNIQUE_HELPER = '''
def resolve_unique(page, builders):
    """Return the first locator that uniquely matches a visible element."""
    for build in builders:
        locator = build()
        try:
            visible = locator.filter(visible=True)
        except TypeError:
            visible = locator
        try:
            count = visible.count()
        except Exception:
            continue
        if count == 1:
            return visible
    raise LookupError("Could not uniquely resolve replay element locator")
'''.strip()


CLICK_RESOLVED_HELPER = f'''
def click_resolved(locator):
    """Playwright click, then JS click on the same node if actionability fails."""
    try:
        locator.evaluate({CENTER_SCROLL_JS!r})
    except Exception:
        pass
    try:
        locator.click(timeout={ELEMENT_CLICK_TIMEOUT_MS})
        return
    except Exception as exc:
        message = str(exc).lower()
        if any(
            marker in message
            for marker in (
                "not attached",
                "element is not attached",
                "target closed",
                "frame was detached",
                "frame has been detached",
            )
        ):
            raise
        locator.evaluate({JS_CLICK_JS!r})
'''.strip()
