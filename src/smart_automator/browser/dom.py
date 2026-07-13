from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Frame, Page as PlaywrightPage

from .util import cap_text_length

# Vendored from nanobrowser chrome-extension/public/buildDomTree.js
BUILD_DOM_TREE_SCRIPT_PATH = Path(__file__).parent / "assets" / "buildDomTree.js"
HIGHLIGHT_CONTAINER_ID = "playwright-highlight-container"

DEFAULT_INCLUDE_ATTRIBUTES = [
    "title",
    "type",
    "checked",
    "name",
    "role",
    "value",
    "placeholder",
    "data-date-format",
    "data-state",
    "alt",
    "aria-checked",
    "aria-label",
    "aria-expanded",
    "href",
]

_SAFE_CSS_ATTRIBUTES = frozenset({
    "id",
    "name",
    "type",
    "placeholder",
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "role",
    "for",
    "autocomplete",
    "required",
    "readonly",
    "alt",
    "title",
    "src",
    "href",
    "target",
})

_DYNAMIC_CSS_ATTRIBUTES = frozenset({"data-id", "data-qa", "data-cy", "data-testid"})


@dataclass
class DOMElementNode:
    tag_name: str
    xpath: str
    attributes: dict[str, str] = field(default_factory=dict)
    children: list[DOMBaseNode] = field(default_factory=list)
    is_visible: bool = False
    is_interactive: bool = False
    is_top_element: bool = False
    is_in_viewport: bool = False
    highlight_index: int | None = None
    is_new: bool | None = None
    shadow_root: bool = False
    parent: DOMElementNode | None = None

    def get_all_text_till_next_clickable_element(self, max_depth: int = -1) -> str:
        parts: list[str] = []

        def collect(node: DOMBaseNode, depth: int):
            if max_depth != -1 and depth > max_depth:
                return
            if isinstance(node, DOMElementNode) and node is not self and node.highlight_index is not None:
                return
            if isinstance(node, DOMTextNode):
                parts.append(node.text)
            elif isinstance(node, DOMElementNode):
                for child in node.children:
                    collect(child, depth + 1)

        collect(self, 0)
        return "\n".join(parts).strip()

    def clickable_elements_to_string(self, include_attributes: list[str] | None = None) -> str:
        attrs = include_attributes or DEFAULT_INCLUDE_ATTRIBUTES
        lines: list[str] = []

        def process_node(node: DOMBaseNode, depth: int):
            next_depth = depth
            depth_str = "\t" * depth

            if isinstance(node, DOMElementNode):
                if node.highlight_index is not None:
                    next_depth += 1
                    text = node.get_all_text_till_next_clickable_element()
                    attr_parts: list[str] = []
                    attributes_to_include: dict[str, str] = {}

                    for key, value in node.attributes.items():
                        if key in attrs and str(value).strip():
                            attributes_to_include[key] = str(value).strip()

                    ordered_keys = [key for key in attrs if key in attributes_to_include]
                    if len(ordered_keys) > 1:
                        keys_to_remove: set[str] = set()
                        seen_values: dict[str, str] = {}
                        for key in ordered_keys:
                            value = attributes_to_include[key]
                            if len(value) > 5:
                                if value in seen_values:
                                    keys_to_remove.add(key)
                                else:
                                    seen_values[value] = key
                        for key in keys_to_remove:
                            del attributes_to_include[key]

                    if node.tag_name == attributes_to_include.get("role"):
                        attributes_to_include.pop("role", None)

                    for attr in ("aria-label", "placeholder", "title"):
                        if (
                            attr in attributes_to_include
                            and attributes_to_include[attr].strip().lower() == text.strip().lower()
                        ):
                            attributes_to_include.pop(attr, None)

                    if attributes_to_include:
                        attr_parts = [
                            f"{key}={cap_text_length(value, 15)}"
                            for key, value in attributes_to_include.items()
                        ]

                    highlight = f"*[{node.highlight_index}]" if node.is_new else f"[{node.highlight_index}]"
                    line = f"{depth_str}{highlight}<{node.tag_name}"
                    if attr_parts:
                        line += " " + " ".join(attr_parts)
                    if text:
                        if not attr_parts:
                            line += " "
                        line += f">{text.strip()}"
                    elif not attr_parts:
                        line += " "
                    line += " />"
                    lines.append(line)

                for child in node.children:
                    process_node(child, next_depth)

            elif isinstance(node, DOMTextNode):
                if node.has_parent_with_highlight_index():
                    return
                if node.parent and node.parent.is_visible and node.parent.is_top_element:
                    lines.append(f"{depth_str}{node.text}")

        process_node(self, 0)
        return "\n".join(lines)

    def convert_simple_xpath_to_css_selector(self) -> str:
        if not self.xpath:
            return ""

        clean_xpath = self.xpath.lstrip("/")
        css_parts: list[str] = []

        for part in clean_xpath.split("/"):
            if not part:
                continue

            if ":" in part and "[" not in part:
                css_parts.append(part.replace(":", "\\:"))
                continue

            if "[" in part:
                bracket_index = part.index("[")
                base_part = part[:bracket_index]
                if ":" in base_part:
                    base_part = base_part.replace(":", "\\:")
                index_part = part[bracket_index:]

                indices = [idx.replace("[", "") for idx in index_part.split("]")[:-1]]
                for idx in indices:
                    if re.fullmatch(r"\d+", idx):
                        index = int(idx) - 1
                        base_part += f":nth-of-type({index + 1})"
                    elif idx == "last()":
                        base_part += ":last-of-type"
                    elif "position()" in idx and ">1" in idx:
                        base_part += ":nth-of-type(n+2)"
                css_parts.append(base_part)
            else:
                css_parts.append(part)

        return " > ".join(css_parts)

    def enhanced_css_selector_for_element(self, include_dynamic_attributes: bool = True) -> str:
        try:
            if not self.xpath:
                return ""

            css_selector = self.convert_simple_xpath_to_css_selector()

            class_value = self.attributes.get("class")
            if class_value and include_dynamic_attributes:
                valid_class_name = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")
                for class_name in class_value.strip().split():
                    if class_name.strip() and valid_class_name.match(class_name):
                        css_selector += f".{class_name}"

            safe_attributes = set(_SAFE_CSS_ATTRIBUTES)
            if include_dynamic_attributes:
                safe_attributes |= _DYNAMIC_CSS_ATTRIBUTES

            for attribute, value in self.attributes.items():
                if attribute == "class" or not attribute.strip():
                    continue
                if attribute not in safe_attributes:
                    continue

                safe_attribute = attribute.replace(":", "\\:")
                if value == "":
                    css_selector += f"[{safe_attribute}]"
                elif re.search(r'["\'<>`\n\r\t]', value):
                    collapsed = re.sub(r"\s+", " ", value).strip()
                    safe_value = collapsed.replace('"', '\\"')
                    css_selector += f'[{safe_attribute}*="{safe_value}"]'
                else:
                    css_selector += f'[{safe_attribute}="{value}"]'

            return css_selector
        except Exception:
            tag_name = self.tag_name or "*"
            return f"{tag_name}[highlightIndex='{self.highlight_index}']"


@dataclass
class DOMTextNode:
    text: str
    is_visible: bool = False
    parent: DOMElementNode | None = None

    def has_parent_with_highlight_index(self) -> bool:
        current = self.parent
        while current is not None:
            if current.highlight_index is not None:
                return True
            current = current.parent
        return False


DOMBaseNode = DOMElementNode | DOMTextNode


@dataclass
class DOMState:
    element_tree: DOMElementNode
    selector_map: dict[int, DOMElementNode] = field(default_factory=dict)


def calc_branch_path_hash_set(state: DOMState | dict[int, DOMElementNode]) -> set[str]:
    hashes: set[str] = set()
    elements = state.values() if isinstance(state, dict) else state.selector_map.values()
    for element in elements:
        segments: list[str] = []
        current: DOMElementNode | None = element
        while current is not None:
            if current.highlight_index is not None:
                segments.append(f"{current.tag_name}:{current.xpath}")
            current = current.parent
        if segments:
            hashes.add("|".join(reversed(segments)))
    return hashes


def branch_hash_is_subset_of(new_hashes: set[str], cached_hashes: set[str]) -> bool:
    return new_hashes.issubset(cached_hashes)


def _read_build_dom_tree_script() -> str:
    return BUILD_DOM_TREE_SCRIPT_PATH.read_text(encoding="utf-8")


_BUILD_DOM_TREE_ARGS = """(args) => window.buildDomTree(args)"""


def ensure_build_dom_tree_script_on_frame(frame: Frame | PlaywrightPage) -> None:
    try:
        already_injected = frame.evaluate("() => typeof window.buildDomTree === 'function'")
        if already_injected:
            return
        script = _read_build_dom_tree_script()
        frame.evaluate(
            """(source) => {
                if (typeof window.buildDomTree === 'function') return;
                const script = document.createElement('script');
                script.textContent = source;
                document.documentElement.appendChild(script);
                script.remove();
            }""",
            script,
        )
    except Exception:
        pass


def inject_build_dom_tree_script(page: PlaywrightPage) -> None:
    """Inject nanobrowser buildDomTree.js once per page context."""
    ensure_build_dom_tree_script_on_frame(page)
    for child_frame in page.frames:
        if child_frame != page.main_frame:
            ensure_build_dom_tree_script_on_frame(child_frame)


def ensure_build_dom_tree_script(page: PlaywrightPage) -> None:
    inject_build_dom_tree_script(page)


def _run_build_dom_tree_raw(
    frame: Frame | PlaywrightPage,
    *,
    show_highlights: bool,
    do_highlight_elements: bool,
    focus_element: int,
    viewport_expansion: int,
    start_highlight_index: int,
    start_id: int,
    debug_mode: bool,
) -> dict[str, Any] | None:
    ensure_build_dom_tree_script_on_frame(frame)
    try:
        return frame.evaluate(
            _BUILD_DOM_TREE_ARGS,
            {
                "showHighlightElements": show_highlights,
                "doHighlightElements": do_highlight_elements,
                "focusHighlightIndex": focus_element,
                "viewportExpansion": viewport_expansion,
                "startHighlightIndex": start_highlight_index,
                "startId": start_id,
                "debugMode": debug_mode,
            },
        )
    except Exception:
        return None


def _get_raw_dom_element_nodes(js_map: dict[str, Any], tag_name: str | None = None) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    for node_id, node_data in js_map.items():
        if not node_data or node_data.get("type") == "TEXT_NODE":
            continue
        if tag_name is not None and node_data.get("tagName") != tag_name:
            continue
        nodes[node_id] = node_data
    return nodes


def _visible_iframes_failed_loading(result: dict[str, Any]) -> dict[str, dict]:
    iframe_nodes = _get_raw_dom_element_nodes(result.get("map", {}), "iframe")
    failed: dict[str, dict] = {}
    for node_id, iframe_node in iframe_nodes.items():
        attributes = iframe_node.get("attributes", {})
        error = attributes.get("error")
        try:
            height = int(attributes.get("computedHeight", 0))
            width = int(attributes.get("computedWidth", 0))
        except (TypeError, ValueError):
            height = 0
            width = 0
        skipped = attributes.get("skipped")
        if error is not None and height > 1 and width > 1 and not skipped:
            failed[node_id] = iframe_node
    return failed


def _get_max_highlight_index(result: dict[str, Any], prior_max: int = -1) -> int:
    values = [
        node.get("highlightIndex", -1)
        for node in result.get("map", {}).values()
        if isinstance(node, dict) and node.get("highlightIndex") is not None
    ]
    return max([prior_max, *values], default=prior_max)


def _get_max_id(result: dict[str, Any], prior_max: int = -1) -> int:
    root_id = int(result.get("rootId", prior_max))
    map_ids = [int(node_id) for node_id in result.get("map", {}).keys() if str(node_id).isdigit()]
    return max([prior_max, root_id, *map_ids], default=prior_max)


def _locate_matching_iframe_node(
    iframe_nodes: dict[str, dict],
    frame_info: dict[str, Any],
    *,
    strict_comparison: bool = True,
) -> dict | None:
    for iframe_node in iframe_nodes.values():
        attributes = iframe_node.get("attributes", {})
        try:
            frame_height = int(attributes.get("computedHeight", 0))
            frame_width = int(attributes.get("computedWidth", 0))
        except (TypeError, ValueError):
            frame_height = 0
            frame_width = 0
        frame_name = attributes.get("name")
        frame_url = attributes.get("src")
        frame_title = attributes.get("title")
        name_match = not frame_name or not frame_info.get("name") or frame_info["name"] == frame_name
        if strict_comparison:
            height_match = frame_info.get("computedHeight") == frame_height
            width_match = frame_info.get("computedWidth") == frame_width
            url_match = not frame_url or not frame_info.get("href") or frame_info["href"] == frame_url
            title_match = not frame_title or not frame_info.get("title") or frame_info["title"] == frame_title
        else:
            height_diff = abs(int(frame_info.get("computedHeight", 0)) - frame_height)
            width_diff = abs(int(frame_info.get("computedWidth", 0)) - frame_width)
            height_match = height_diff < 10 or height_diff / max(
                int(frame_info.get("computedHeight", 0)), frame_height, 1
            ) < 0.1
            width_match = width_diff < 10 or width_diff / max(
                int(frame_info.get("computedWidth", 0)), frame_width, 1
            ) < 0.1
            url_match = True
            title_match = True
        if height_match and width_match and name_match and url_match and title_match:
            return iframe_node
    if strict_comparison:
        return _locate_matching_iframe_node(iframe_nodes, frame_info, strict_comparison=False)
    return None


def _get_frame_info(frame: Frame) -> dict[str, Any] | None:
    try:
        return frame.evaluate(
            """() => ({
                computedHeight: window.innerHeight,
                computedWidth: window.innerWidth,
                href: window.location.href,
                name: window.name,
                title: document.title,
            })"""
        )
    except Exception:
        return None


def _construct_frame_tree(
    page: PlaywrightPage,
    parent_frame_page: dict[str, Any],
    all_frames_info: list[tuple[Frame, dict[str, Any]]],
    *,
    show_highlights: bool,
    do_highlight_elements: bool,
    focus_element: int,
    viewport_expansion: int,
    debug_mode: bool,
    starting_node_id: int,
    starting_highlight_index: int,
) -> tuple[int, int, dict[str, Any]]:
    parent_iframes_failed = _visible_iframes_failed_loading(parent_frame_page)
    failed_frames = [
        (frame, info)
        for frame, info in all_frames_info
        if _locate_matching_iframe_node(parent_iframes_failed, info) is not None
    ]

    max_node_id = starting_node_id
    max_highlight_index = starting_highlight_index

    for frame, frame_info in failed_frames:
        sub_frame_page = _run_build_dom_tree_raw(
            frame,
            show_highlights=show_highlights,
            do_highlight_elements=do_highlight_elements,
            focus_element=focus_element,
            viewport_expansion=viewport_expansion,
            start_highlight_index=max_highlight_index + 1,
            start_id=max_node_id + 1,
            debug_mode=debug_mode,
        )
        if not sub_frame_page or not sub_frame_page.get("map") or not sub_frame_page.get("rootId"):
            continue

        max_node_id = _get_max_id(sub_frame_page, max_node_id)
        max_highlight_index = _get_max_highlight_index(sub_frame_page, max_highlight_index)

        parent_frame_page["map"] = {
            **parent_frame_page.get("map", {}),
            **sub_frame_page.get("map", {}),
        }

        iframe_node = _locate_matching_iframe_node(parent_iframes_failed, frame_info)
        if iframe_node is not None:
            iframe_node.setdefault("children", []).append(sub_frame_page["rootId"])

        children_failed = _visible_iframes_failed_loading(sub_frame_page)
        if children_failed:
            child_frames_info = [
                (child_frame, info)
                for child_frame, info in all_frames_info
                if child_frame != frame
            ]
            max_node_id, max_highlight_index, parent_frame_page = _construct_frame_tree(
                page,
                sub_frame_page,
                child_frames_info,
                show_highlights=show_highlights,
                do_highlight_elements=do_highlight_elements,
                focus_element=focus_element,
                viewport_expansion=viewport_expansion,
                debug_mode=debug_mode,
                starting_node_id=max_node_id,
                starting_highlight_index=max_highlight_index,
            )

    return max_node_id, max_highlight_index, parent_frame_page


def _deserialize_dom_tree(result: dict[str, Any]) -> DOMState:
    if not result or not result.get("rootId"):
        empty_tree = DOMElementNode(tag_name="body", xpath="/body")
        return DOMState(element_tree=empty_tree)

    js_map = result["map"]
    root_id = result["rootId"]
    node_map: dict[str, DOMBaseNode] = {}
    selector_map: dict[int, DOMElementNode] = {}

    for nid, data in js_map.items():
        if data.get("type") == "TEXT_NODE":
            node_map[nid] = DOMTextNode(text=data["text"], is_visible=data.get("isVisible", False))
        else:
            node = DOMElementNode(
                tag_name=data["tagName"],
                xpath=data.get("xpath", ""),
                attributes=data.get("attributes", {}),
                is_visible=data.get("isVisible", False),
                is_interactive=data.get("isInteractive", False),
                is_top_element=data.get("isTopElement", False),
                is_in_viewport=data.get("isInViewport", False),
                highlight_index=data.get("highlightIndex"),
                is_new=data.get("isNew"),
                shadow_root=data.get("shadowRoot", False),
            )
            node_map[nid] = node
            if node.highlight_index is not None:
                selector_map[node.highlight_index] = node

    for nid, node in node_map.items():
        if isinstance(node, DOMElementNode):
            data = js_map[nid]
            for child_id in data.get("children", []):
                if child_id in node_map:
                    child = node_map[child_id]
                    if hasattr(child, "parent"):
                        child.parent = node
                    node.children.append(child)

    root = node_map.get(root_id)
    if not root or not isinstance(root, DOMElementNode):
        root = DOMElementNode(tag_name="body", xpath="/body")

    return DOMState(element_tree=root, selector_map=selector_map)


def build_dom_tree(
    page: PlaywrightPage,
    show_highlights: bool = True,
    focus_element: int = -1,
    viewport_expansion: int = 0,
    start_highlight_index: int = 0,
    start_id: int = 0,
    debug_mode: bool = False,
    do_highlight_elements: bool | None = None,
) -> DOMState:
    ensure_build_dom_tree_script(page)
    if do_highlight_elements is None:
        do_highlight_elements = show_highlights

    main_frame_result = _run_build_dom_tree_raw(
        page.main_frame,
        show_highlights=show_highlights,
        do_highlight_elements=do_highlight_elements,
        focus_element=focus_element,
        viewport_expansion=viewport_expansion,
        start_highlight_index=start_highlight_index,
        start_id=start_id,
        debug_mode=debug_mode,
    )
    if not main_frame_result or not main_frame_result.get("map") or not main_frame_result.get("rootId"):
        empty_tree = DOMElementNode(tag_name="body", xpath="/body")
        return DOMState(element_tree=empty_tree)

    failed_iframes = _visible_iframes_failed_loading(main_frame_result)
    if failed_iframes:
        frames_info: list[tuple[Frame, dict[str, Any]]] = []
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            info = _get_frame_info(frame)
            if info is not None:
                frames_info.append((frame, info))
        if frames_info:
            _, _, main_frame_result = _construct_frame_tree(
                page,
                main_frame_result,
                frames_info,
                show_highlights=show_highlights,
                do_highlight_elements=do_highlight_elements,
                focus_element=focus_element,
                viewport_expansion=viewport_expansion,
                debug_mode=debug_mode,
                starting_node_id=_get_max_id(main_frame_result),
                starting_highlight_index=_get_max_highlight_index(main_frame_result),
            )

    return _deserialize_dom_tree(main_frame_result)


def mark_new_elements(current: DOMState, previous_hashes: set[str] | None) -> None:
    if not previous_hashes:
        return
    for element in current.selector_map.values():
        segments: list[str] = []
        node: DOMElementNode | None = element
        while node is not None:
            if node.highlight_index is not None:
                segments.append(f"{node.tag_name}:{node.xpath}")
            node = node.parent
        branch_hash = "|".join(reversed(segments))
        element.is_new = branch_hash not in previous_hashes


def remove_highlights(page: PlaywrightPage):
    cleanup_js = f"""() => {{
        if (window._highlightCleanupFunctions && window._highlightCleanupFunctions.length) {{
            window._highlightCleanupFunctions.forEach(fn => {{
                try {{ fn(); }} catch (e) {{}}
            }});
            window._highlightCleanupFunctions = [];
        }}
        const container = document.getElementById('{HIGHLIGHT_CONTAINER_ID}');
        if (container) container.remove();
        const highlightedElements = document.querySelectorAll('[browser-user-highlight-id^="playwright-highlight-"]');
        for (const el of Array.from(highlightedElements)) {{
            el.removeAttribute('browser-user-highlight-id');
        }}
    }}"""
    for frame in page.frames:
        try:
            frame.evaluate(cleanup_js)
        except Exception:
            pass
