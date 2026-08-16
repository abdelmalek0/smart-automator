from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .dom import DOMElementNode, DOMTextNode
from .locators import (
    css_id_selector,
    duplicate_set_selector,
    effective_unlabeled_kind,
    has_neighbor_fingerprint,
    inferred_role,
    is_unstable_id,
    neighbor_fingerprint_matches,
    nth_count_replayable,
    relative_xpath,
    split_locator_candidates,
    testid_from_attrs,
    unlabeled_set_kind,
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
    nested_identity: str | None = None
    locator_chain: list[dict] = field(default_factory=list)
    duplicate_set: dict | None = None

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
        if self.nested_identity:
            payload["nestedIdentity"] = self.nested_identity
        if self.locator_chain:
            payload["locatorChain"] = list(self.locator_chain)
        if self.duplicate_set:
            payload["duplicateSet"] = dict(self.duplicate_set)
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
            nested_identity=data.get("nestedIdentity", data.get("nested_identity")),
            locator_chain=list(data.get("locatorChain") or data.get("locator_chain") or []),
            duplicate_set=data.get("duplicateSet", data.get("duplicate_set")),
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


def _tree_root(dom_element: DOMElementNode) -> DOMElementNode:
    current = dom_element
    while current.parent is not None:
        current = current.parent
    return current


def _iter_element_nodes(node: DOMElementNode):
    yield node
    for child in node.children:
        if isinstance(child, DOMElementNode):
            yield from _iter_element_nodes(child)


def _node_accessible_name(node: DOMElementNode) -> str | None:
    text = node.get_all_text_till_next_clickable_element().strip() or None
    if text:
        return text
    for key in ("aria-label", "title", "placeholder", "name", "alt"):
        value = (node.attributes.get(key) or "").strip()
        if value:
            return value
    return None


def extract_nested_identity(node: DOMElementNode) -> str | None:
    for key in ("alt", "title"):
        value = (node.attributes.get(key) or "").strip()
        if value:
            return value
    labelled = (node.attributes.get("aria-labelledby") or "").strip()
    if labelled:
        root = _tree_root(node)
        for candidate in _iter_element_nodes(root):
            if (candidate.attributes.get("id") or "").strip() == labelled:
                name = _node_accessible_name(candidate)
                if name:
                    return name

    found: list[str] = []

    def walk(current: DOMElementNode) -> None:
        tag = (current.tag_name or "").lower()
        if tag in {"title", "desc"}:
            text = current.get_all_text_till_next_clickable_element().strip()
            if text:
                found.append(text)
                return
        for key in ("alt", "title"):
            value = (current.attributes.get(key) or "").strip()
            if value:
                found.append(value)
                return
        for child in current.children:
            if isinstance(child, DOMElementNode):
                walk(child)
            elif isinstance(child, DOMTextNode) and tag in {"title", "desc"}:
                text = child.text.strip()
                if text:
                    found.append(text)

    walk(node)
    return found[0] if found else None


def _element_siblings(node: DOMElementNode) -> list[DOMElementNode]:
    parent = node.parent
    if parent is None:
        return []
    return [child for child in parent.children if isinstance(child, DOMElementNode)]


def _neighbor_fingerprint(node: DOMElementNode) -> dict:
    parent = node.parent
    parent_tag = (parent.tag_name or "").lower() if parent is not None else ""
    siblings = _element_siblings(node)
    try:
        idx = siblings.index(node)
    except ValueError:
        idx = -1
    prev_tag = (siblings[idx - 1].tag_name or "").lower() if idx > 0 else ""
    next_tag = (
        (siblings[idx + 1].tag_name or "").lower()
        if 0 <= idx < len(siblings) - 1
        else ""
    )
    return {
        "parentTag": parent_tag,
        "siblingCount": len(siblings),
        "prevTag": prev_tag,
        "nextTag": next_tag,
    }


def _unique_nodes(root: DOMElementNode, predicate) -> list[DOMElementNode]:
    return [node for node in _iter_element_nodes(root) if predicate(node)]


def _ancestor_contains_only_target(
    ancestor: DOMElementNode,
    target: DOMElementNode,
    duplicates: list[DOMElementNode],
) -> bool:
    contained = [node for node in duplicates if _is_ancestor_or_self(ancestor, node)]
    return contained == [target]


def _is_ancestor_or_self(ancestor: DOMElementNode, node: DOMElementNode) -> bool:
    current: DOMElementNode | None = node
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def _fork_ancestor(
    target: DOMElementNode,
    duplicates: list[DOMElementNode],
) -> DOMElementNode | None:
    current = target.parent
    while current is not None:
        if _ancestor_contains_only_target(current, target, duplicates):
            return current
        current = current.parent
    return None


def _build_locator_capture(
    dom_element: DOMElementNode,
) -> tuple[list[dict], dict | None, str | None]:
    root = _tree_root(dom_element)
    attrs = dom_element.attributes or {}
    nested = extract_nested_identity(dom_element)
    accessible = _node_accessible_name(dom_element) or nested
    role = inferred_role(dom_element.tag_name, attrs)
    chain: list[dict] = []

    def unique(predicate) -> bool:
        matches = _unique_nodes(root, predicate)
        return len(matches) == 1 and matches[0] is dom_element

    testid = testid_from_attrs(attrs)
    if testid and unique(lambda node: testid_from_attrs(node.attributes) == testid):
        chain.append({"kind": "testid", "attr": testid[0], "value": testid[1]})
        return chain, None, nested

    element_id = (attrs.get("id") or "").strip()
    if element_id and not is_unstable_id(element_id):
        if unique(lambda node: (node.attributes.get("id") or "").strip() == element_id):
            chain.append({"kind": "css", "selector": css_id_selector(element_id)})
            return chain, None, nested

    if role and accessible:
        def role_name_match(node: DOMElementNode) -> bool:
            node_role = inferred_role(node.tag_name, node.attributes)
            name = _node_accessible_name(node) or extract_nested_identity(node)
            return node_role == role and bool(name) and name == accessible

        if unique(role_name_match):
            chain.append({"kind": "role", "role": role, "name": accessible})
            return chain, None, nested

    label = (attrs.get("aria-label") or "").strip()
    if label and unique(lambda node: (node.attributes.get("aria-label") or "").strip() == label):
        chain.append({"kind": "label", "label": label})
        return chain, None, nested

    placeholder = (attrs.get("placeholder") or "").strip()
    if placeholder and unique(
        lambda node: (node.attributes.get("placeholder") or "").strip() == placeholder
    ):
        chain.append({"kind": "placeholder", "placeholder": placeholder})
        return chain, None, nested

    if nested and unique(lambda node: extract_nested_identity(node) == nested):
        chain.append({"kind": "text", "text": nested})
        return chain, None, nested

    stable_root, rel_xpath = _stable_root_for_element(dom_element)
    if stable_root and rel_xpath:
        chain.append({"kind": "relative", "root": stable_root, "xpath": rel_xpath})
        return chain, None, nested

    explicit_role = (attrs.get("role") or "").strip() or None
    selector = duplicate_set_selector(dom_element.tag_name, role=explicit_role)
    duplicates = _nth_matches_in_tree(
        root,
        (dom_element.tag_name or "*").lower(),
        explicit_role,
    )
    fork = _fork_ancestor(dom_element, duplicates) if len(duplicates) > 1 else None
    if fork is not None:
        fork_testid = testid_from_attrs(fork.attributes)
        fork_id = (fork.attributes.get("id") or "").strip()
        rel = relative_xpath(fork.xpath, dom_element.xpath)
        if fork_testid and rel:
            attr, value = fork_testid
            chain.append({"kind": "relative", "root": f'[{attr}="{value}"]', "xpath": rel})
            return chain, None, nested
        if fork_id and not is_unstable_id(fork_id) and rel:
            chain.append({"kind": "relative", "root": css_id_selector(fork_id), "xpath": rel})
            return chain, None, nested
        fork_label = (fork.attributes.get("aria-label") or "").strip()
        if fork_label and rel:
            chain.append({
                "kind": "relative",
                "root": f'{fork.tag_name}[aria-label="{fork_label}"]',
                "xpath": rel,
            })
            return chain, None, nested

    if not duplicates or dom_element not in duplicates:
        duplicates = [dom_element]
    index = duplicates.index(dom_element) + 1
    count = len(duplicates)
    position = unlabeled_set_kind(index, count)
    neighbors = _neighbor_fingerprint(dom_element)
    duplicate = {
        "selector": selector,
        "index": index,
        "count": count,
        "position": position,
        "tag": (dom_element.tag_name or "").lower(),
        "role": explicit_role or role or "",
        **neighbors,
    }
    chain.append({
        "kind": position,
        "selector": selector,
        "index": index,
        "count": count,
        **neighbors,
    })
    return chain, duplicate, nested


def convert_dom_element_to_history_element(dom_element: DOMElementNode) -> DOMHistoryElement:
    nested = extract_nested_identity(dom_element)
    accessible_name = _node_accessible_name(dom_element) or nested
    stable_root, rel_xpath = _stable_root_for_element(dom_element)
    locator_chain, duplicate_set, nested = _build_locator_capture(dom_element)
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
        nested_identity=nested,
        locator_chain=locator_chain,
        duplicate_set=duplicate_set,
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
    if dom_history_element.locator_chain or dom_history_element.duplicate_set:
        return True
    if (dom_history_element.nested_identity or "").strip():
        return True
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
    if (dom_history_element.stable_root or "").strip() and (dom_history_element.relative_xpath or "").strip():
        return True
    return False


def _nth_params_from_history(dom_history_element: DOMHistoryElement) -> dict | None:
    for item in dom_history_element.locator_chain or []:
        if isinstance(item, dict) and item.get("kind") in {"nth", "first", "last"}:
            params = {str(k): v for k, v in item.items() if k != "kind"}
            params["kind"] = item["kind"]
            return params
    if isinstance(dom_history_element.duplicate_set, dict):
        payload = dict(dom_history_element.duplicate_set)
        try:
            index = int(payload.get("index") or 0)
            count = int(payload.get("count") or 0)
        except (TypeError, ValueError):
            index, count = 0, 0
        payload.setdefault(
            "kind",
            payload.get("position") or unlabeled_set_kind(index, count),
        )
        return payload
    return None


def _nth_selector_parts(selector: str) -> tuple[str, str | None]:
    tag = selector.split("[", 1)[0].split(".", 1)[0] or "*"
    role = None
    if '[role="' in selector:
        role = selector.split('[role="', 1)[1].split('"', 1)[0]
    return tag, role


def _nth_structure_matches(
    params: dict,
    node: DOMElementNode,
    tree: DOMElementNode,
) -> bool:
    selector = str(params.get("selector") or "")
    tag, role = _nth_selector_parts(selector)
    expected_count = int(params.get("count") or 0)
    matches = _nth_matches_in_tree(tree, tag, role)
    if not nth_count_replayable(len(matches), expected_count):
        return False
    kind = effective_unlabeled_kind(str(params.get("kind") or "nth"), params)
    if kind in {"first", "last"}:
        return True
    if has_neighbor_fingerprint(params):
        return neighbor_fingerprint_matches(params, _neighbor_fingerprint(node))
    return True


def _nth_matches_in_tree(
    tree: DOMElementNode,
    selector_tag: str,
    role: str | None,
) -> list[DOMElementNode]:
    tag = (selector_tag or "*").lower()
    matches: list[DOMElementNode] = []
    for node in _iter_element_nodes(tree):
        node_tag = (node.tag_name or "").lower()
        if tag not in {"", "*"} and node_tag != tag:
            continue
        if role:
            node_role = (node.attributes.get("role") or "").strip() or inferred_role(
                node.tag_name, node.attributes
            )
            if node_role != role:
                continue
        matches.append(node)
    return matches


def _resolve_locator_kind_in_tree(
    kind: str,
    params: dict,
    tree: DOMElementNode,
) -> DOMElementNode | None:
    if kind == "testid":
        return find_element_by_testid_in_tree(str(params.get("attr") or ""), str(params.get("value") or ""), tree)
    if kind == "css":
        selector = str(params.get("selector") or "")
        if selector.startswith("#"):
            return find_element_by_id_in_tree(selector[1:], tree)
        if selector.startswith("[id=\""):
            element_id = selector[len('[id="'):-2]
            return find_element_by_id_in_tree(element_id, tree)
        if "[name=\"" in selector:
            name = selector.split('[name="', 1)[1].split('"', 1)[0]
            tag = selector.split("[", 1)[0] or "*"
            return _unique_tree_match(
                tree,
                lambda node: (
                    (tag in {"", "*"} or (node.tag_name or "").lower() == tag.lower())
                    and (node.attributes.get("name") or "") == name
                ),
            )
        if "[aria-label=\"" in selector:
            label = selector.split('[aria-label="', 1)[1].split('"', 1)[0]
            return find_element_by_aria_label_in_tree(label, tree)
        return None
    if kind == "label":
        return find_element_by_aria_label_in_tree(str(params.get("label") or ""), tree)
    if kind == "placeholder":
        placeholder = str(params.get("placeholder") or "").strip()
        if not placeholder:
            return None
        return _unique_tree_match(
            tree,
            lambda node: (node.attributes.get("placeholder") or "").strip() == placeholder,
        )
    if kind == "role":
        role = str(params.get("role") or "")
        name = str(params.get("name") or "")
        if not role or not name:
            return None
        return _unique_tree_match(
            tree,
            lambda node: (
                inferred_role(node.tag_name, node.attributes) == role
                and (_node_accessible_name(node) or extract_nested_identity(node) or "") == name
            ),
        )
    if kind == "text":
        text = str(params.get("text") or "").strip()
        if not text:
            return None
        return _unique_tree_match(
            tree,
            lambda node: (
                (_node_accessible_name(node) or "") == text
                or (extract_nested_identity(node) or "") == text
            ),
        )
    if kind == "relative":
        root_selector = str(params.get("root") or "")
        rel = str(params.get("xpath") or "")
        if not root_selector or not rel:
            return None
        root_node = _resolve_locator_kind_in_tree("css", {"selector": root_selector}, tree)
        if root_node is None and root_selector.startswith("["):
            # testid form [data-testid="x"]
            if "=" in root_selector:
                attr = root_selector[1:].split("=", 1)[0]
                value = root_selector.split("=", 1)[1].strip('"]')
                root_node = find_element_by_testid_in_tree(attr, value, tree)
        if root_node is None:
            return None
        for node in _iter_element_nodes(root_node):
            actual = relative_xpath(root_node.xpath, node.xpath)
            if actual == rel:
                return node
        return None
    if kind in {"nth", "first", "last"}:
        expected_count = int(params.get("count") or 0)
        selector = str(params.get("selector") or "")
        tag, role = _nth_selector_parts(selector)
        matches = _nth_matches_in_tree(tree, tag, role)
        if not nth_count_replayable(len(matches), expected_count):
            return None
        effective = effective_unlabeled_kind(kind, params)
        if effective == "first":
            return matches[0] if matches else None
        if effective == "last":
            return matches[-1] if matches else None
        index = int(params.get("index") or 0)
        if index < 1 or index > len(matches):
            return None
        chosen = matches[index - 1]
        if has_neighbor_fingerprint(params):
            actual = _neighbor_fingerprint(chosen)
            if not neighbor_fingerprint_matches(params, actual):
                return None
        return chosen
    if kind == "xpath":
        return find_element_by_xpath_in_tree(str(params.get("xpath") or ""), tree)
    return None


def resolve_history_element_in_tree(
    dom_history_element: DOMHistoryElement,
    tree: DOMElementNode,
) -> DOMElementNode | None:
    """Resolve a recorded element using the captured chain, then unique xpath."""
    resolved = find_history_element_in_tree(dom_history_element, tree)
    if resolved is not None:
        nth = _nth_params_from_history(dom_history_element)
        if nth is None:
            return resolved
        kind = effective_unlabeled_kind(str(nth.get("kind") or "nth"), nth)
        if kind not in {"first", "last"} and _nth_structure_matches(nth, resolved, tree):
            return resolved

    step = {"element": dom_history_element.to_dict(), "args": {}}
    identity, positional = split_locator_candidates(step)
    for kind, params in identity:
        resolved = _resolve_locator_kind_in_tree(kind, params, tree)
        if resolved is not None:
            return resolved

    if identity or _history_has_identity(dom_history_element):
        return None

    for kind, params in positional:
        if kind == "xpath":
            resolved = find_element_by_xpath_in_tree(str(params.get("xpath") or ""), tree)
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
