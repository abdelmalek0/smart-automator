from __future__ import annotations

import re

from .dom import DOMBaseNode, DOMElementNode, DOMTextNode

_SUBMIT_PATTERN = re.compile(
    r"\b(submit|sign\s*in|log\s*in|enter|ok|confirm|continue|next|search|go)\b",
    re.IGNORECASE,
)
_INPUT_TAGS = frozenset({"input", "textarea", "select"})
_INTERACTIVE_TAGS = frozenset({"button", "a", "input", "textarea", "select"})
_IGNORED_ROLES = frozenset({"presentation", "none", "generic"})
_TEXT_BEARING_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "dt", "dd", "label",
    "blockquote", "figcaption", "caption", "pre",
    "span", "em", "strong", "small", "b", "i",
    "flt-semantics",
})
_MAX_VISIBLE_TEXT_CHARS = 4000
_VISIBLE_TEXT_BUDGET_RATIO = 0.35
_MIN_VISIBLE_TEXT_LEN = 2


def _normalize_visible_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _element_label(node: DOMElementNode) -> str:
    text = node.get_all_text_till_next_clickable_element()
    if text:
        return text.strip().lower()
    for attr in ("aria-label", "placeholder", "title", "value", "name"):
        value = node.attributes.get(attr, "").strip()
        if value:
            return value.lower()
    return ""


def _has_element_children(node: DOMElementNode) -> bool:
    return any(isinstance(child, DOMElementNode) for child in node.children)


def _is_leaf_text_div(node: DOMElementNode) -> bool:
    return node.tag_name.lower() == "div" and not _has_element_children(node)


def _is_text_bearing(node: DOMElementNode) -> bool:
    return node.tag_name.lower() in _TEXT_BEARING_TAGS or _is_leaf_text_div(node)


def _has_accessible_identity(node: DOMElementNode) -> bool:
    if (node.attributes.get("aria-label") or "").strip():
        return True
    role = (node.attributes.get("role") or "").strip().lower()
    if role and role not in _IGNORED_ROLES:
        return True
    if node.tag_name.lower() != "flt-semantics":
        return False
    if (node.attributes.get("title") or "").strip():
        return True
    return bool(node.get_all_text_till_next_clickable_element().strip())


def _should_keep_static_text(parent: DOMElementNode | None) -> bool:
    if parent is None:
        return False
    if _has_accessible_identity(parent):
        return True
    if not parent.is_visible:
        return False
    if parent.is_top_element:
        return True
    return _is_text_bearing(parent)


def _has_direct_text_child(node: DOMElementNode) -> bool:
    return any(
        isinstance(child, DOMTextNode) and bool(child.text.strip())
        for child in node.children
    )


def _priority_score(node: DOMElementNode) -> int:
    score = 0
    if node.is_new:
        score += 100
    tag = node.tag_name.lower()
    label = _element_label(node)
    if tag in _INPUT_TAGS:
        score += 80
    if tag == "button" or node.attributes.get("role") == "button":
        score += 60
    if tag == "a" and node.attributes.get("href"):
        score += 40
    if _SUBMIT_PATTERN.search(label):
        score += 50
    if node.attributes.get("type") in {"submit", "button"}:
        score += 30
    if node.is_in_viewport:
        score += 10
    return score


def _collect_clickable_lines(
    root: DOMElementNode,
    include_attributes: list[str],
) -> list[tuple[int, int, bool, str]]:
    """Return (priority, highlight_index, is_in_viewport, line) for clickables.

    Text-only lines use highlight_index=-1 and is_in_viewport=True.
    """
    collected: list[tuple[int, int, bool, str]] = []

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
                    if key in include_attributes and str(value).strip():
                        attributes_to_include[key] = str(value).strip()

                ordered_keys = [key for key in include_attributes if key in attributes_to_include]
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
                    from .util import cap_text_length

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
                if not node.is_in_viewport:
                    line += " (offscreen)"
                priority = _priority_score(node)
                collected.append((priority, node.highlight_index, node.is_in_viewport, line))
            elif _should_keep_static_text(node):
                emitted_attr = False
                for attr in ("aria-label", "title"):
                    value = (node.attributes.get(attr) or "").strip()
                    if value:
                        collected.append((0, -1, True, f"{depth_str}{value}"))
                        emitted_attr = True
                        break
                if not emitted_attr and not _has_direct_text_child(node):
                    aggregated = node.get_all_text_till_next_clickable_element().strip()
                    if aggregated:
                        collected.append((0, -1, True, f"{depth_str}{aggregated}"))

            for child in node.children:
                process_node(child, next_depth)

        elif isinstance(node, DOMTextNode):
            if node.has_parent_with_highlight_index():
                return
            if _should_keep_static_text(node.parent):
                collected.append((0, -1, True, f"{depth_str}{node.text}"))

    process_node(root, 0)
    return collected


def _collect_clickable_labels(root: DOMElementNode) -> set[str]:
    labels: set[str] = set()

    def walk(node: DOMBaseNode) -> None:
        if isinstance(node, DOMElementNode):
            if node.highlight_index is not None:
                label = _element_label(node)
                if label:
                    labels.add(label)
                text = _normalize_visible_text(node.get_all_text_till_next_clickable_element())
                if text:
                    labels.add(text.lower())
            for child in node.children:
                walk(child)

    walk(root)
    return labels


def _filter_visible_text_lines(
    text_lines: list[tuple[int, int, bool, str]],
    clickable_labels: set[str],
) -> list[str]:
    seen: set[str] = set()
    filtered: list[str] = []

    for _, _, _, line in text_lines:
        normalized = _normalize_visible_text(line.strip("\t"))
        if len(normalized) < _MIN_VISIBLE_TEXT_LEN:
            continue
        key = normalized.lower()
        if key in clickable_labels or key in seen:
            continue
        seen.add(key)
        filtered.append(normalized)

    return filtered


def _reserved_visible_text_budget(max_chars: int, *, no_interactives: bool, text_lines: list[str]) -> int:
    if not text_lines:
        return 0
    if no_interactives:
        return min(_MAX_VISIBLE_TEXT_CHARS, max_chars)
    return min(_MAX_VISIBLE_TEXT_CHARS, int(max_chars * _VISIBLE_TEXT_BUDGET_RATIO))


def _render_visible_text_section(
    text_lines: list[str],
    *,
    char_budget: int,
) -> tuple[list[str], int]:
    if not text_lines or char_budget <= 0:
        return [], 0

    text_budget = min(_MAX_VISIBLE_TEXT_CHARS, char_budget)
    if text_budget <= 0:
        return [], 0

    rendered: list[str] = ["[Visible text]"]
    remaining = text_budget
    shown = 0
    for line in text_lines:
        if remaining <= 0:
            break
        entry = line
        if len(entry) > remaining:
            entry = entry[:remaining]
        rendered.append(entry)
        remaining -= len(entry) + 1
        shown += 1

    if shown < len(text_lines):
        omitted = len(text_lines) - shown
        note = f"... truncated {omitted} of {len(text_lines)} visible text lines"
        if len(note) <= remaining:
            rendered.append(note)

    return rendered, shown


def _select_elements_viewport_first(
    element_lines: list[tuple[int, int, bool, str]],
    *,
    max_elements: int,
) -> list[tuple[int, int, bool, str]]:
    """Prefer in-viewport elements, then fill remaining budget with off-screen."""
    in_viewport = [item for item in element_lines if item[2]]
    offscreen = [item for item in element_lines if not item[2]]
    in_viewport.sort(key=lambda item: (-item[0], item[1]))
    offscreen.sort(key=lambda item: (-item[0], item[1]))

    selected = in_viewport[:max_elements]
    remaining = max_elements - len(selected)
    if remaining > 0:
        selected.extend(offscreen[:remaining])
    selected.sort(key=lambda item: item[1])
    return selected


def bounded_clickable_elements_to_string(
    root: DOMElementNode,
    include_attributes: list[str],
    *,
    max_elements: int = 120,
    max_chars: int = 16000,
) -> tuple[str, int, int]:
    """Render clickable DOM with priority cap and visible static text. Returns (text, shown_count, total_count)."""
    lines = _collect_clickable_lines(root, include_attributes)
    element_lines = [item for item in lines if item[1] >= 0]
    text_lines = [item for item in lines if item[1] < 0]
    total_count = len(element_lines)
    offscreen_total = sum(1 for item in element_lines if not item[2])

    clickable_labels = _collect_clickable_labels(root)
    filtered_text = _filter_visible_text_lines(text_lines, clickable_labels)
    reserved_for_text = _reserved_visible_text_budget(
        max_chars,
        no_interactives=total_count == 0,
        text_lines=filtered_text,
    )

    rendered: list[str] = []
    char_budget = max(max_chars - reserved_for_text, 0)
    shown = 0

    if total_count > 0:
        selected = _select_elements_viewport_first(element_lines, max_elements=max_elements)
        offscreen_shown = 0

        for _, _, in_vp, line in selected:
            if char_budget <= 0:
                break
            if len(line) > char_budget:
                line = line[:char_budget]
            rendered.append(line)
            char_budget -= len(line) + 1
            shown += 1
            if not in_vp:
                offscreen_shown += 1

        if shown < total_count:
            omitted = total_count - shown
            offscreen_omitted = max(offscreen_total - offscreen_shown, 0)
            index_range = f"[{selected[0][1]}..{selected[-1][1]}]" if selected else "[]"
            note = (
                f"... truncated {omitted} of {total_count} elements; "
                f"shown indexes {index_range}."
            )
            if offscreen_omitted:
                note += f" {offscreen_omitted} offscreen interactives omitted."
            note += (
                " Use scroll actions if the needed control is not listed "
                "(truncated or not yet mounted)."
            )
            if char_budget > 0 and len(note) <= char_budget:
                rendered.append(note)
                char_budget -= len(note) + 1
            elif reserved_for_text <= 0:
                rendered.append(note)

    visible_section, _ = _render_visible_text_section(
        filtered_text,
        char_budget=reserved_for_text + max(char_budget, 0),
    )
    if visible_section:
        if rendered:
            rendered.append("")
        rendered.extend(visible_section)

    if not rendered:
        return "", shown, total_count

    return "\n".join(rendered), shown, total_count
