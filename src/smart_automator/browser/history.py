from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .dom import DOMElementNode


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

    def to_dict(self) -> dict:
        return {
            "tagName": self.tag_name,
            "xpath": self.xpath,
            "highlightIndex": self.highlight_index,
            "entireParentBranchPath": self.entire_parent_branch_path,
            "attributes": self.attributes,
            "shadowRoot": self.shadow_root,
            "cssSelector": self.css_selector,
        }

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


def convert_dom_element_to_history_element(dom_element: DOMElementNode) -> DOMHistoryElement:
    return DOMHistoryElement(
        tag_name=dom_element.tag_name,
        xpath=dom_element.xpath,
        highlight_index=dom_element.highlight_index,
        entire_parent_branch_path=get_parent_branch_path(dom_element),
        attributes=dict(dom_element.attributes),
        shadow_root=dom_element.shadow_root,
        css_selector=dom_element.enhanced_css_selector_for_element(),
    )


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


def find_element_by_id_in_tree(element_id: str, tree: DOMElementNode) -> DOMElementNode | None:
    target_id = (element_id or "").strip()
    if not target_id:
        return None

    def walk(node: DOMElementNode) -> DOMElementNode | None:
        if node.attributes.get("id") == target_id:
            return node
        for child in node.children:
            if isinstance(child, DOMElementNode):
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(tree)


def find_element_by_aria_label_in_tree(label: str, tree: DOMElementNode) -> DOMElementNode | None:
    target_label = (label or "").strip()
    if not target_label:
        return None

    def walk(node: DOMElementNode) -> DOMElementNode | None:
        if node.attributes.get("aria-label") == target_label:
            return node
        for child in node.children:
            if isinstance(child, DOMElementNode):
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(tree)


def resolve_history_element_in_tree(
    dom_history_element: DOMHistoryElement,
    tree: DOMElementNode,
) -> DOMElementNode | None:
    """Resolve a recorded element using the same fallback order as replay scripts."""
    resolved = find_history_element_in_tree(dom_history_element, tree)
    if resolved is not None:
        return resolved

    aria_label = dom_history_element.attributes.get("aria-label")
    if aria_label:
        resolved = find_element_by_aria_label_in_tree(aria_label, tree)
        if resolved is not None:
            return resolved

    element_id = dom_history_element.attributes.get("id")
    if element_id:
        resolved = find_element_by_id_in_tree(element_id, tree)
        if resolved is not None:
            return resolved

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
