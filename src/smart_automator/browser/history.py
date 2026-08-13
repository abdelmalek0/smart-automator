from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .dom import DOMElementNode
from .locators import (
    css_id_selector,
    inferred_role,
    is_unstable_id,
    relative_xpath,
    testid_from_attrs,
)


@dataclass
class HashedDomElement:
    branch_path_hash: str
    attributes_hash: str
    xpath_hash: str


@dataclass
class DOMHistoryElement:
    tag_name: str
    xpath: str
    highlight_index: int | None
    entire_parent_branch_path: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    shadow_root: bool = False
    css_selector: str | None = None
    accessible_name: str | None = None
    frame_path: list[str] = field(default_factory=list)
    stable_root: str | None = None
    relative_xpath: str | None = None

    def to_dict(self) -> dict:
        payload = {
            "tagName": self.tag_name,
            "xpath": self.xpath,
            "highlightIndex": self.highlight_index,
            "entireParentBranchPath": self.entire_parent_branch_path,
            "attributes": self.attributes,
            "shadowRoot": self.shadow_root,
            "cssSelector": self.css_selector,
            "framePath": list(self.frame_path),
        }
        if self.accessible_name:
            payload["accessibleName"] = self.accessible_name
        if self.stable_root:
            payload["stableRoot"] = self.stable_root
        if self.relative_xpath:
            payload["relativeXPath"] = self.relative_xpath
        role = inferred_role(self.tag_name, self.attributes)
        if role and "role" not in self.attributes:
            payload["inferredRole"] = role
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> DOMHistoryElement:
        return cls(
            tag_name=data.get("tagName", data.get("tag_name", "")),
            xpath=data.get("xpath", ""),
            highlight_index=data.get("highlightIndex", data.get("highlight_index")),
            entire_parent_branch_path=data.get(
                "entireParentBranchPath", data.get("entire_parent_branch_path", [])
            ),
            attributes=data.get("attributes", {}),
            shadow_root=data.get("shadowRoot", data.get("shadow_root", False)),
            css_selector=data.get("cssSelector", data.get("css_selector")),
            accessible_name=data.get("accessibleName", data.get("accessible_name")),
            frame_path=list(data.get("framePath") or data.get("frame_path") or []),
            stable_root=data.get("stableRoot", data.get("stable_root")),
            relative_xpath=data.get("relativeXPath", data.get("relative_xpath")),
        )


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_parent_branch_path(dom_element: DOMElementNode) -> list[str]:
    parents: list[DOMElementNode] = []
    current: DOMElementNode | None = dom_element
    while current is not None and current.parent is not None:
        parents.append(current)
        current = current.parent
    parents.reverse()
    return [parent.tag_name for parent in parents]


def hash_dom_element(dom_element: DOMElementNode) -> HashedDomElement:
    parent_branch_path = get_parent_branch_path(dom_element)
    branch_path_hash = _sha256_hex("/".join(parent_branch_path))
    attributes_string = "".join(f"{key}={value}" for key, value in dom_element.attributes.items())
    attributes_hash = _sha256_hex(attributes_string)
    xpath_hash = _sha256_hex(dom_element.xpath or "")
    return HashedDomElement(branch_path_hash, attributes_hash, xpath_hash)


def hash_dom_history_element(dom_history_element: DOMHistoryElement) -> HashedDomElement:
    branch_path_hash = _sha256_hex("/".join(dom_history_element.entire_parent_branch_path))
    attributes_string = "".join(
        f"{key}={value}" for key, value in dom_history_element.attributes.items()
    )
    attributes_hash = _sha256_hex(attributes_string)
    xpath_hash = _sha256_hex(dom_history_element.xpath or "")
    return HashedDomElement(branch_path_hash, attributes_hash, xpath_hash)


def _frame_path_for_element(dom_element: DOMElementNode) -> list[str]:
    frames: list[str] = []
    current: DOMElementNode | None = dom_element.parent
    while current is not None:
        if current.tag_name == "iframe" and current.xpath:
            frames.append(current.xpath)
        current = current.parent
    frames.reverse()
    return frames


def _stable_root_for_element(dom_element: DOMElementNode) -> tuple[str | None, str | None]:
    current = dom_element.parent
    while current is not None:
        testid = testid_from_attrs(current.attributes)
        if testid:
            attr, value = testid
            root = f'[{attr}="{value}"]'
            rel = relative_xpath(current.xpath, dom_element.xpath)
            return root, rel
        element_id = (current.attributes.get("id") or "").strip()
        if element_id and not is_unstable_id(element_id):
            rel = relative_xpath(current.xpath, dom_element.xpath)
            return css_id_selector(element_id), rel
        current = current.parent
    return None, None


def convert_dom_element_to_history_element(dom_element: DOMElementNode) -> DOMHistoryElement:
    accessible_name = dom_element.get_all_text_till_next_clickable_element().strip() or None
    if not accessible_name:
        for key in ("aria-label", "title", "placeholder", "name", "alt"):
            value = (dom_element.attributes.get(key) or "").strip()
            if value:
                accessible_name = value
                break
    stable_root, rel_xpath = _stable_root_for_element(dom_element)
    return DOMHistoryElement(
        tag_name=dom_element.tag_name,
        xpath=dom_element.xpath,
        highlight_index=dom_element.highlight_index,
        entire_parent_branch_path=get_parent_branch_path(dom_element),
        attributes=dict(dom_element.attributes),
        shadow_root=dom_element.shadow_root,
        css_selector=dom_element.enhanced_css_selector_for_element(),
        accessible_name=accessible_name,
        frame_path=_frame_path_for_element(dom_element),
        stable_root=stable_root,
        relative_xpath=rel_xpath,
    )


def enhanced_css_selector_for_history_element(
    dom_history_element: DOMHistoryElement,
    *,
    include_dynamic_attributes: bool = True,
) -> str:
    dom_node = DOMElementNode(
        tag_name=dom_history_element.tag_name,
        xpath=dom_history_element.xpath,
        attributes=dict(dom_history_element.attributes),
        shadow_root=dom_history_element.shadow_root,
    )
    return dom_node.enhanced_css_selector_for_element(include_dynamic_attributes)


def compare_history_element_and_dom_element(
    dom_history_element: DOMHistoryElement,
    dom_element: DOMElementNode,
) -> bool:
    hashed_history = hash_dom_history_element(dom_history_element)
    hashed_element = hash_dom_element(dom_element)
    return (
        hashed_history.branch_path_hash == hashed_element.branch_path_hash
        and hashed_history.attributes_hash == hashed_element.attributes_hash
        and hashed_history.xpath_hash == hashed_element.xpath_hash
    )


def find_history_element_in_tree(
    dom_history_element: DOMHistoryElement,
    tree: DOMElementNode,
) -> DOMElementNode | None:
    hashed_history = hash_dom_history_element(dom_history_element)

    def process_node(node: DOMElementNode) -> DOMElementNode | None:
        if node.highlight_index is not None:
            hashed_node = hash_dom_element(node)
            if (
                hashed_node.branch_path_hash == hashed_history.branch_path_hash
                and hashed_node.attributes_hash == hashed_history.attributes_hash
                and hashed_node.xpath_hash == hashed_history.xpath_hash
            ):
                return node
        for child in node.children:
            if isinstance(child, DOMElementNode):
                found = process_node(child)
                if found is not None:
                    return found
        return None

    return process_node(tree)


def _normalize_xpath(xpath: str) -> str:
    return (xpath or "").strip().lstrip("/")


def find_element_by_xpath_in_tree(xpath: str, tree: DOMElementNode) -> DOMElementNode | None:
    target = _normalize_xpath(xpath)
    if not target:
        return None

    def walk(node: DOMElementNode) -> DOMElementNode | None:
        if _normalize_xpath(node.xpath or "") == target:
            return node
        for child in node.children:
            if isinstance(child, DOMElementNode):
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(tree)


def _unique_tree_match(
    tree: DOMElementNode,
    predicate,
) -> DOMElementNode | None:
    matches: list[DOMElementNode] = []

    def walk(node: DOMElementNode) -> None:
        if predicate(node):
            matches.append(node)
        for child in node.children:
            if isinstance(child, DOMElementNode):
                walk(child)

    walk(tree)
    if len(matches) == 1:
        return matches[0]
    return None


def find_element_by_id_in_tree(element_id: str, tree: DOMElementNode) -> DOMElementNode | None:
    target_id = (element_id or "").strip()
    if not target_id or is_unstable_id(target_id):
        return None
    return _unique_tree_match(tree, lambda node: node.attributes.get("id") == target_id)


def find_element_by_aria_label_in_tree(label: str, tree: DOMElementNode) -> DOMElementNode | None:
    target_label = (label or "").strip()
    if not target_label:
        return None
    return _unique_tree_match(
        tree,
        lambda node: node.attributes.get("aria-label") == target_label,
    )


def find_element_by_testid_in_tree(
    attr: str,
    value: str,
    tree: DOMElementNode,
) -> DOMElementNode | None:
    target = (value or "").strip()
    if not attr or not target:
        return None
    return _unique_tree_match(tree, lambda node: node.attributes.get(attr) == target)


def _history_has_identity(dom_history_element: DOMHistoryElement) -> bool:
    attrs = dom_history_element.attributes or {}
    if testid_from_attrs(attrs):
        return True
    element_id = (attrs.get("id") or "").strip()
    if element_id and not is_unstable_id(element_id):
        return True
    if (attrs.get("aria-label") or "").strip():
        return True
    if (attrs.get("placeholder") or "").strip():
        return True
    if (dom_history_element.accessible_name or "").strip():
        return True
    input_type = (attrs.get("type") or "").strip().lower()
    if (attrs.get("name") or "").strip() and input_type not in {"radio", "checkbox"}:
        return True
    return False


def resolve_history_element_in_tree(
    dom_history_element: DOMHistoryElement,
    tree: DOMElementNode,
) -> DOMElementNode | None:
    """Resolve a recorded element using identity first, then unique xpath."""
    resolved = find_history_element_in_tree(dom_history_element, tree)
    if resolved is not None:
        return resolved

    testid = testid_from_attrs(dom_history_element.attributes)
    if testid:
        resolved = find_element_by_testid_in_tree(testid[0], testid[1], tree)
        if resolved is not None:
            return resolved

    element_id = dom_history_element.attributes.get("id")
    if element_id:
        resolved = find_element_by_id_in_tree(element_id, tree)
        if resolved is not None:
            return resolved

    aria_label = dom_history_element.attributes.get("aria-label")
    if aria_label:
        resolved = find_element_by_aria_label_in_tree(aria_label, tree)
        if resolved is not None:
            return resolved

    if _history_has_identity(dom_history_element):
        return None

    if dom_history_element.xpath:
        return find_element_by_xpath_in_tree(dom_history_element.xpath, tree)

    return None


def is_file_uploader(element_node: DOMElementNode, max_depth: int = 3, current_depth: int = 0) -> bool:
    if current_depth > max_depth:
        return False
    if element_node.tag_name == "input":
        attributes = element_node.attributes
        input_type = attributes.get("type", "").lower()
        if input_type == "file" or attributes.get("accept"):
            return True
    if current_depth < max_depth:
        for child in element_node.children:
            if isinstance(child, DOMElementNode) and is_file_uploader(child, max_depth, current_depth + 1):
                return True
    return False
