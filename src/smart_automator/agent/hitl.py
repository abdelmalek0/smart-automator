from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..browser.history import DOMHistoryElement, enhanced_css_selector_for_history_element
from ..browser.locators import (
    css_id_selector,
    duplicate_set_selector,
    inferred_role,
    is_unstable_id,
    testid_from_attrs,
    unlabeled_set_kind,
)
from .context import ActionResult, AgentContext, PendingHitlHandoff
from .history import AgentStepRecord, BrowserStateHistory

log = logging.getLogger(__name__)


def _hitl_identity_allowed(unique: dict[str, Any] | None, key: str) -> bool:
    if unique is None:
        return True
    return bool(unique.get(key))


def _nth_locator_from_hitl(
    element: DOMHistoryElement,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = {}
    if isinstance(payload, dict):
        candidate = payload.get("nth") or payload.get("duplicateSet") or payload.get("duplicate_set")
        if isinstance(candidate, dict):
            raw = candidate
    role_attr = (element.attributes.get("role") or "").strip() or None
    selector = str(raw.get("selector") or "").strip()
    if not selector:
        selector = duplicate_set_selector(element.tag_name, role=role_attr)
    try:
        index = int(raw.get("index") or 1)
        count = int(raw.get("count") or 1)
    except (TypeError, ValueError):
        index, count = 1, 1
    index = max(1, index)
    count = max(count, index)
    kind = str(raw.get("kind") or raw.get("position") or unlabeled_set_kind(index, count))
    if kind not in {"first", "last", "nth"}:
        kind = unlabeled_set_kind(index, count)
    item: dict[str, Any] = {
        "kind": kind,
        "selector": selector,
        "index": index,
        "count": count,
    }
    for key in ("parentTag", "siblingCount", "prevTag", "nextTag"):
        if key in raw:
            item[key] = raw[key]
    return item


def _locator_chain_from_hitl_element(
    element: DOMHistoryElement,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    attrs = element.attributes or {}
    unique = None
    nth_raw = None
    if isinstance(payload, dict):
        unique_payload = payload.get("identityUnique") or payload.get("identity_unique")
        if isinstance(unique_payload, dict):
            unique = unique_payload
        nth_raw = payload.get("nth") or payload.get("duplicateSet") or payload.get("duplicate_set")

    testid = testid_from_attrs(attrs)
    if testid and _hitl_identity_allowed(unique, "testid"):
        return [{"kind": "testid", "attr": testid[0], "value": testid[1]}]
    element_id = (attrs.get("id") or "").strip()
    if element_id and not is_unstable_id(element_id) and _hitl_identity_allowed(unique, "id"):
        return [{"kind": "css", "selector": css_id_selector(element_id)}]
    if element.stable_root and element.relative_xpath:
        return [{
            "kind": "relative",
            "root": element.stable_root,
            "xpath": element.relative_xpath,
        }]
    if label := (attrs.get("aria-label") or "").strip():
        if _hitl_identity_allowed(unique, "ariaLabel"):
            return [{"kind": "label", "label": label}]
    if placeholder := (attrs.get("placeholder") or "").strip():
        if _hitl_identity_allowed(unique, "placeholder"):
            return [{"kind": "placeholder", "placeholder": placeholder}]
    if nested := (element.nested_identity or "").strip():
        if _hitl_identity_allowed(unique, "nested"):
            return [{"kind": "text", "text": nested}]
    role = inferred_role(element.tag_name, attrs)
    name = (element.accessible_name or "").strip()
    use_name = (
        _hitl_identity_allowed(unique, "roleName")
        if unique is not None
        else not isinstance(nth_raw, dict)
    )
    if role and name and use_name:
        return [{"kind": "role", "role": role, "name": name}]
    if name and use_name:
        return [{"kind": "text", "text": name}]
    return [_nth_locator_from_hitl(element, payload)]

_HUMAN_CAPTURE_SCRIPT = """
(() => {
  if (window.__saHitlCaptureInstalled) return;
  window.__saHitlCaptureInstalled = true;

  const ATTRS = [
    'title', 'type', 'checked', 'name', 'role', 'value', 'placeholder',
    'data-date-format', 'data-state', 'alt', 'aria-checked', 'aria-label',
    'aria-expanded', 'href', 'id', 'data-testid', 'data-cy', 'data-test', 'data-qa',
  ];

  function isInteractiveElement(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = element.tagName.toLowerCase();
    if (['button', 'a', 'input', 'textarea', 'select', 'label'].includes(tag)) return true;
    const role = element.getAttribute('role');
    if (role && ['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'textbox', 'combobox'].includes(role)) {
      return true;
    }
    if (element.hasAttribute('flt-tappable')) return true;
    if (element.getAttribute('tabindex') === '0') return true;
    if (element.getAttribute('aria-label')) return true;
    return false;
  }

  function resolveInteractiveTarget(element) {
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      if (isInteractiveElement(current)) return current;
      current = current.parentElement;
    }
    return element;
  }

  function getElementPosition(currentElement) {
    if (!currentElement.parentElement) return 0;
    const tagName = currentElement.nodeName.toLowerCase();
    const siblings = Array.from(currentElement.parentElement.children).filter(
      (sib) => sib.nodeName.toLowerCase() === tagName,
    );
    if (siblings.length === 1) return 0;
    return siblings.indexOf(currentElement) + 1;
  }

  function getXPath(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return '';
    const segments = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      const tag = current.tagName.toLowerCase();
      const position = getElementPosition(current);
      segments.unshift(position > 0 ? `${tag}[${position}]` : tag);
      current = current.parentElement;
    }
    return segments.join('/');
  }

  function isUnstableId(value) {
    if (!value) return true;
    if (value.startsWith('flt-semantic-node-')) return true;
    if (/^mui-\\d+$/.test(value)) return true;
    if (/^ember\\d+$/.test(value)) return true;
    if (/^:r[\\w-]*:$/i.test(value)) return true;
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) return true;
    if (/^[a-f0-9]{8,}$/i.test(value)) return true;
    return false;
  }

  function relativeXPath(ancestorXPath, nodeXPath) {
    const ancestor = (ancestorXPath || '').replace(/^\\/+|\\/+$/g, '');
    const node = (nodeXPath || '').replace(/^\\/+|\\/+$/g, '');
    if (!ancestor || !node) return '';
    if (node === ancestor) return '.';
    const prefix = ancestor + '/';
    if (node.startsWith(prefix)) return './' + node.slice(prefix.length);
    return '';
  }

  function cssIdSelector(elementId) {
    if (/^[A-Za-z_][\\w-]*$/.test(elementId)) return '#' + elementId;
    return '[id="' + elementId.replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"') + '"]';
  }

  function stableRootFor(element) {
    let current = element.parentElement;
    const nodeXPath = getXPath(element);
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      for (const attr of ['data-testid', 'data-cy', 'data-test', 'data-qa']) {
        const value = (current.getAttribute(attr) || '').trim();
        if (value) {
          const rel = relativeXPath(getXPath(current), nodeXPath);
          if (rel) return { stableRoot: '[' + attr + '="' + value + '"]', relativeXPath: rel };
        }
      }
      const elementId = (current.getAttribute('id') || '').trim();
      if (elementId && !isUnstableId(elementId)) {
        const rel = relativeXPath(getXPath(current), nodeXPath);
        if (rel) return { stableRoot: cssIdSelector(elementId), relativeXPath: rel };
      }
      current = current.parentElement;
    }
    return {};
  }

  function nestedIdentity(element) {
    const alt = (element.getAttribute('alt') || '').trim();
    if (alt) return alt;
    const title = (element.getAttribute('title') || '').trim();
    if (title) return title;
    const svgTitle = element.querySelector && element.querySelector('svg title, title, desc');
    if (svgTitle) {
      const text = (svgTitle.textContent || '').replace(/\\s+/g, ' ').trim();
      if (text) return text;
    }
    const img = element.querySelector && element.querySelector('img[alt]');
    if (img) {
      const imgAlt = (img.getAttribute('alt') || '').trim();
      if (imgAlt) return imgAlt;
    }
    return '';
  }

  function isDisplayed(element) {
    if (!(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function inferredRole(tag, attrs) {
    const explicit = ((attrs && attrs.role) || '').trim().toLowerCase();
    if (explicit && explicit !== 'presentation' && explicit !== 'none' && explicit !== 'generic') {
      return explicit;
    }
    tag = (tag || '').toLowerCase();
    if (tag === 'input') {
      const inputType = ((attrs && attrs.type) || 'text').toLowerCase() || 'text';
      const types = {
        button: 'button', submit: 'button', reset: 'button', checkbox: 'checkbox',
        radio: 'radio', range: 'slider', file: 'button',
      };
      return types[inputType] || 'textbox';
    }
    const tags = { button: 'button', a: 'link', select: 'combobox', textarea: 'textbox', summary: 'button' };
    return tags[tag] || '';
  }

  function duplicateSetSelector(tag, roleAttr) {
    tag = (tag || '*').toLowerCase() || '*';
    const role = (roleAttr || '').trim();
    if (role && role !== inferredRole(tag, {})) return tag + '[role="' + role + '"]';
    return tag;
  }

  function isInteractive(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = (node.tagName || '').toLowerCase();
    if (['a', 'button', 'input', 'select', 'textarea', 'summary'].includes(tag)) return true;
    const role = (node.getAttribute('role') || '').trim().toLowerCase();
    return ['button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'tab', 'menuitem'].includes(role);
  }

  function neighborName(node) {
    if (!node) return '';
    const aria = (node.getAttribute('aria-label') || '').trim();
    const nested = nestedIdentity(node);
    const visible = visibleText(node);
    const placeholder = (node.getAttribute('placeholder') || '').trim();
    const name = (node.getAttribute('name') || '').trim();
    const associated = associatedLabel(node);
    return clipText(aria || nested || visible || placeholder || name || associated, 80);
  }

  function neighborFingerprint(element) {
    const parent = element.parentElement;
    const parentTag = parent ? parent.tagName.toLowerCase() : '';
    const siblings = parent
      ? Array.from(parent.children).filter((node) => node.nodeType === 1)
      : [];
    const idx = siblings.indexOf(element);
    let prevInteractive = null;
    let nextInteractive = null;
    for (let i = idx - 1; i >= 0; i--) {
      if (isInteractive(siblings[i])) {
        prevInteractive = siblings[i];
        break;
      }
    }
    for (let i = idx + 1; i < siblings.length; i++) {
      if (isInteractive(siblings[i])) {
        nextInteractive = siblings[i];
        break;
      }
    }
    const selfRect = element.getBoundingClientRect();
    function peerMeta(node) {
      if (!node) return { name: '', relation: '' };
      const name = neighborName(node);
      if (!isCoherentPhrase(name)) return { name: '', relation: '' };
      const rect = node.getBoundingClientRect();
      if (!boxesClose(selfRect, rect, LANDMARK_CLOSE_PX)) return { name: '', relation: '' };
      return { name: name, relation: relationOf(selfRect, rect) };
    }
    const prevMeta = peerMeta(prevInteractive);
    const nextMeta = peerMeta(nextInteractive);
    return {
      parentTag,
      siblingCount: siblings.length,
      prevTag: idx > 0 ? siblings[idx - 1].tagName.toLowerCase() : '',
      nextTag: (idx >= 0 && idx < siblings.length - 1) ? siblings[idx + 1].tagName.toLowerCase() : '',
      prevName: prevMeta.name,
      nextName: nextMeta.name,
      prevRelation: prevMeta.relation,
      nextRelation: nextMeta.relation,
    };
  }

  function nthPinpoint(element) {
    const tag = element.tagName.toLowerCase();
    const roleAttr = (element.getAttribute('role') || '').trim();
    const selector = duplicateSetSelector(tag, roleAttr);
    let matches;
    try {
      matches = Array.from(document.querySelectorAll(selector)).filter(isDisplayed);
    } catch (err) {
      matches = [];
    }
    let index = matches.indexOf(element) + 1;
    let count = matches.length;
    if (index < 1) {
      try {
        matches = Array.from(document.querySelectorAll(selector));
      } catch (err) {
        matches = [];
      }
      index = matches.indexOf(element) + 1;
      count = matches.length;
      if (index < 1) {
        index = 1;
        count = Math.max(count, 1);
      }
    }
    const position = (count >= 2 && index === 1)
      ? 'first'
      : (count >= 2 && index === count)
        ? 'last'
        : 'nth';
    return { selector, index, count, kind: position, position, ...neighborFingerprint(element) };
  }

  function attrMatches(attr, value) {
    if (!value) return 0;
    const escaped = String(value).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
    try {
      return document.querySelectorAll('[' + attr + '="' + escaped + '"]').length;
    } catch (err) {
      return 0;
    }
  }

  function accessibleNameOf(element) {
    const aria = (element.getAttribute('aria-label') || '').trim();
    if (aria) return aria;
    const nested = nestedIdentity(element);
    if (nested) return nested;
    return visibleText(element);
  }

  function roleNameUnique(element, role, name) {
    if (!role || !name) return false;
    const matches = [];
    for (const el of document.querySelectorAll('*')) {
      if (!isDisplayed(el)) continue;
      const attrs = {
        role: el.getAttribute('role') || '',
        type: el.getAttribute('type') || '',
      };
      if (inferredRole(el.tagName.toLowerCase(), attrs) !== role) continue;
      if (accessibleNameOf(el) !== name) continue;
      matches.push(el);
      if (matches.length > 1) return false;
    }
    return matches.length === 1 && matches[0] === element;
  }

  function identityUnique(element, attrs, nested, name) {
    const unique = {};
    for (const attr of ['data-testid', 'data-cy', 'data-test', 'data-qa']) {
      const value = (attrs[attr] || '').trim();
      if (value) {
        unique.testid = attrMatches(attr, value) === 1;
        break;
      }
    }
    const elementId = (attrs.id || '').trim();
    if (elementId && !isUnstableId(elementId)) {
      unique.id = attrMatches('id', elementId) === 1;
    }
    if ((attrs['aria-label'] || '').trim()) {
      unique.ariaLabel = attrMatches('aria-label', attrs['aria-label']) === 1;
    }
    if ((attrs.placeholder || '').trim()) {
      unique.placeholder = attrMatches('placeholder', attrs.placeholder) === 1;
    }
    if (nested) {
      let count = 0;
      for (const el of document.querySelectorAll('*')) {
        if (nestedIdentity(el) === nested) {
          count += 1;
          if (count > 1) break;
        }
      }
      unique.nested = count === 1;
    }
    const role = inferredRole(element.tagName.toLowerCase(), attrs);
    if (role && name) unique.roleName = roleNameUnique(element, role, name);
    if (name) unique.name = unique.roleName || false;
    return unique;
  }

  function framePath(element) {
    const frames = [];
    let win = element.ownerDocument && element.ownerDocument.defaultView;
    while (win && win.frameElement) {
      frames.unshift(getXPath(win.frameElement));
      win = win.parent;
    }
    return frames;
  }

  function collectAttributes(element) {
    const attrs = {};
    for (const name of ATTRS) {
      const value = element.getAttribute(name);
      if (value != null && value !== '') attrs[name] = value;
    }
    return attrs;
  }

  function clipText(text, max) {
    const value = (text || '').replace(/\\s+/g, ' ').trim();
    return value ? value.slice(0, max) : '';
  }

  function visibleText(element) {
    function walk(node) {
      if (!node) return '';
      if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
      if (node.nodeType !== Node.ELEMENT_NODE) return '';
      if (node !== element && isInteractive(node)) return '';
      let out = '';
      for (const child of node.childNodes) out += walk(child);
      return out;
    }
    return clipText(walk(element), 120);
  }

  const LANDMARK_MAX_CHARS = 48;
  const LANDMARK_MAX_WORDS = 6;
  const LANDMARK_CLOSE_PX = 80;

  function isCoherentPhrase(text) {
    const value = clipText(text, 80);
    if (!value || value.length > LANDMARK_MAX_CHARS) return false;
    const words = value.split(/\\s+/).filter(Boolean);
    if (words.length > LANDMARK_MAX_WORDS) return false;
    let numeric = 0;
    for (const word of words) {
      if (/^\\d{1,4}$/.test(word)) numeric += 1;
    }
    return numeric < 3;
  }

  function boxesClose(a, b, maxGap) {
    if (!a || !b) return false;
    const overlapX = a.left < b.right && a.right > b.left;
    const overlapY = a.top < b.bottom && a.bottom > b.top;
    const gapX = overlapX ? 0 : Math.min(Math.abs(a.left - b.right), Math.abs(b.left - a.right));
    const gapY = overlapY ? 0 : Math.min(Math.abs(a.top - b.bottom), Math.abs(b.top - a.bottom));
    if (overlapX) return gapY <= maxGap;
    if (overlapY) return gapX <= maxGap;
    return gapX <= maxGap && gapY <= maxGap;
  }

  function relationOf(fromRect, toRect) {
    const dx = (toRect.left + toRect.width / 2) - (fromRect.left + fromRect.width / 2);
    const dy = (toRect.top + toRect.height / 2) - (fromRect.top + fromRect.height / 2);
    if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? 'left' : 'right';
    return dy > 0 ? 'above' : 'below';
  }

  function nodeRect(node) {
    if (!node) return null;
    if (node.nodeType === Node.TEXT_NODE) {
      const range = document.createRange();
      range.selectNodeContents(node);
      return range.getBoundingClientRect();
    }
    if (node.getBoundingClientRect) return node.getBoundingClientRect();
    return null;
  }

  function associatedLabel(element) {
    const doc = element.ownerDocument || document;
    const labelledBy = (element.getAttribute('aria-labelledby') || '').trim();
    if (labelledBy) {
      const parts = [];
      for (const id of labelledBy.split(/\\s+/)) {
        const node = doc.getElementById(id);
        const text = node ? visibleText(node) : '';
        if (text) parts.push(text);
      }
      if (parts.length) return parts.join(' ');
    }
    const elementId = (element.getAttribute('id') || '').trim();
    if (elementId) {
      try {
        const escaped = elementId.replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
        const forLabel = doc.querySelector('label[for="' + escaped + '"]');
        const text = forLabel ? visibleText(forLabel) : '';
        if (text) return text;
      } catch (err) {}
    }
    const wrapping = element.closest && element.closest('label');
    if (wrapping) {
      const text = visibleText(wrapping);
      if (text) return text;
    }
    let current = element.parentElement;
    while (current && current !== doc.body) {
      if ((current.tagName || '').toLowerCase() === 'fieldset') {
        const legend = current.querySelector('legend');
        const text = legend ? visibleText(legend) : '';
        if (text) return text;
        break;
      }
      current = current.parentElement;
    }
    return '';
  }

  function landmarkFromNode(element, node) {
    if (!node) return null;
    if (node.nodeType === Node.ELEMENT_NODE) {
      if (node.contains(element) || isInteractive(node)) return null;
    }
    const text = node.nodeType === Node.TEXT_NODE
      ? clipText(node.textContent || '', 80)
      : visibleText(node);
    if (!isCoherentPhrase(text)) return null;
    const selfRect = element.getBoundingClientRect();
    const otherRect = nodeRect(node);
    if (!boxesClose(selfRect, otherRect, LANDMARK_CLOSE_PX)) return null;
    return { text: text, relation: relationOf(selfRect, otherRect) };
  }

  function nearbyLandmark(element) {
    let prev = element.previousSibling;
    while (prev) {
      const found = landmarkFromNode(element, prev);
      if (found) return found;
      prev = prev.previousSibling;
    }
    let next = element.nextSibling;
    while (next) {
      const found = landmarkFromNode(element, next);
      if (found) return found;
      next = next.nextSibling;
    }
    return null;
  }

  function spatialRegion(element) {
    const rect = element.getBoundingClientRect();
    const vw = window.innerWidth || 1;
    const vh = window.innerHeight || 1;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const horiz = cx < vw / 3 ? 'left' : (cx > (2 * vw) / 3 ? 'right' : 'center');
    const vert = cy < vh / 3 ? 'top' : (cy > (2 * vh) / 3 ? 'bottom' : 'middle');
    return vert + '-' + horiz;
  }

  function pageUrl() {
    try {
      return location.href || '';
    } catch (err) {
      return '';
    }
  }

  function pageTitle() {
    try {
      return document.title || '';
    } catch (err) {
      return '';
    }
  }

  function elementPayload(element, extra = {}) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
    const roots = stableRootFor(element);
    const nested = nestedIdentity(element);
    const attrs = collectAttributes(element);
    const label = visibleText(element) || nested;
    const nth = nthPinpoint(element);
    const nearby = nearbyLandmark(element);
    return {
      tagName: element.tagName.toLowerCase(),
      xpath: getXPath(element),
      framePath: framePath(element),
      attributes: attrs,
      value: element.value ?? '',
      inputType: element.type ?? '',
      label,
      nestedIdentity: nested,
      associatedLabel: associatedLabel(element),
      nearbyText: nearby ? nearby.text : '',
      nearbyRelation: nearby ? nearby.relation : '',
      spatial: { region: spatialRegion(element) },
      url: pageUrl(),
      title: pageTitle(),
      stableRoot: roots.stableRoot || '',
      relativeXPath: roots.relativeXPath || '',
      nth,
      identityUnique: identityUnique(element, attrs, nested, label),
      ...extra,
    };
  }

  function report(type, element, extra = {}) {
    const payload = elementPayload(element, { eventType: type, ...extra });
    if (!payload) return;
    try {
      window._saHumanAction(payload);
    } catch (err) {
      console.debug('HITL capture failed', err);
    }
  }

  const pendingInputs = new Map();

  function flushInput(xpath) {
    const entry = pendingInputs.get(xpath);
    if (!entry) return;
    pendingInputs.delete(xpath);
    report('input', entry.element, { text: entry.value });
  }

  document.addEventListener('click', (event) => {
    const target = event.target;
    if (!target || target.closest('#playwright-highlight-container')) return;
    const element = resolveInteractiveTarget(target);
    report('click', element);
  }, true);

  document.addEventListener('input', (event) => {
    const target = event.target;
    if (!target || !(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    const xpath = getXPath(target);
    pendingInputs.set(xpath, { element: target, value: target.value });
  }, true);

  document.addEventListener('change', (event) => {
    const target = event.target;
    if (!target) return;
    if (target instanceof HTMLSelectElement) {
      const option = target.selectedOptions[0];
      report('select', target, { text: option ? option.text : target.value });
      return;
    }
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      flushInput(getXPath(target));
    }
  }, true);

  document.addEventListener('keydown', (event) => {
    if (!['Enter', 'Tab', 'Escape'].includes(event.key)) return;
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      flushInput(getXPath(target));
    }
    report('keydown', target, { keys: event.key });
  }, true);

  document.addEventListener('blur', (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      flushInput(getXPath(target));
    }
  }, true);

  let pendingScroll = null;
  let scrollTimer = null;
  const SCROLL_DEBOUNCE_MS = 400;

  function resolveScrollTarget(eventTarget) {
    if (
      !eventTarget ||
      eventTarget === document ||
      eventTarget === document.documentElement ||
      eventTarget === document.body
    ) {
      return { kind: 'window', element: document.documentElement };
    }
    if (eventTarget instanceof HTMLElement) {
      return { kind: 'element', element: eventTarget };
    }
    return { kind: 'window', element: document.documentElement };
  }

  function computeScrollPercent(kind, el) {
    if (kind === 'window') {
      const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
      const scrollHeight = Math.max(
        document.documentElement.scrollHeight || 0,
        document.body ? document.body.scrollHeight : 0,
      );
      const scrollable = Math.max(scrollHeight - (window.innerHeight || 0), 1);
      return Math.max(0, Math.min(100, Math.round((scrollY / scrollable) * 100)));
    }
    const scrollable = Math.max(el.scrollHeight - el.clientHeight, 1);
    return Math.max(0, Math.min(100, Math.round((el.scrollTop / scrollable) * 100)));
  }

  function flushScroll() {
    if (!pendingScroll) return;
    const { kind, element, percent } = pendingScroll;
    pendingScroll = null;
    if (kind === 'window') {
      try {
        window._saHumanAction({
          eventType: 'scroll',
          scrollKind: 'window',
          percent,
          tagName: 'html',
          xpath: '',
          attributes: {},
          label: '',
          url: pageUrl(),
          title: pageTitle(),
        });
      } catch (err) {
        console.debug('HITL scroll capture failed', err);
      }
      return;
    }
    report('scroll', element, { percent, scrollKind: 'element' });
  }

  document.addEventListener(
    'scroll',
    (event) => {
      const resolved = resolveScrollTarget(event.target);
      const percent = computeScrollPercent(resolved.kind, resolved.element);
      pendingScroll = {
        kind: resolved.kind,
        element: resolved.element,
        percent,
      };
      if (scrollTimer) clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        scrollTimer = null;
        flushScroll();
      }, SCROLL_DEBOUNCE_MS);
    },
    true,
  );

  window.__saFlushPendingScrolls = () => {
    if (scrollTimer) {
      clearTimeout(scrollTimer);
      scrollTimer = null;
    }
    flushScroll();
  };

  window.__saFlushPendingInputs = () => {
    for (const xpath of Array.from(pendingInputs.keys())) {
      flushInput(xpath);
    }
    if (window.__saFlushPendingScrolls) window.__saFlushPendingScrolls();
  };
})();
"""

_FLUSH_PENDING_INPUTS_SCRIPT = (
    "(() => { if (window.__saFlushPendingInputs) window.__saFlushPendingInputs(); })();"
)


@dataclass
class _HitlCommand:
    action: str
    kwargs: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    error: str | None = None
    cancelled: bool = False


class HumanActionRecorder:
    """Records human browser interactions via injected capture script."""

    def __init__(
        self,
        context: AgentContext,
        on_action: Callable[[ActionResult, str, dict[str, Any]], None] | None = None,
    ):
        self._context = context
        self._on_action = on_action
        self._active = False
        self._binding_registered_contexts: set[int] = set()
        self._init_script_registered_contexts: set[int] = set()
        self._nav_handlers: dict[int, Callable] = {}
        self._active_page_id: int | None = None
        self._lock = threading.Lock()
        self._recorded: list[tuple[str, dict[str, Any], ActionResult]] = []
        self._last_url = ""

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def recorded(self) -> list[tuple[str, dict[str, Any], ActionResult]]:
        return list(self._recorded)

    def _iter_all_pages(self):
        browser_context = self._context.browser_context
        for page_id in browser_context.get_all_tab_ids():
            try:
                yield browser_context.get_page(page_id)
            except Exception:
                continue

    def _ensure_context_setup(self, playwright_page) -> None:
        pw_context = playwright_page.context
        context_key = id(pw_context)

        if context_key not in self._binding_registered_contexts:
            def _binding_handler(_source: Any, payload: dict[str, Any]) -> None:
                self._handle_capture_event(payload)

            pw_context.expose_binding("_saHumanAction", _binding_handler)
            self._binding_registered_contexts.add(context_key)

        if context_key not in self._init_script_registered_contexts:
            pw_context.add_init_script(_HUMAN_CAPTURE_SCRIPT)
            self._init_script_registered_contexts.add(context_key)

    def _inject_capture_script(self, playwright_page) -> None:
        self._ensure_context_setup(playwright_page)
        playwright_page.evaluate(_HUMAN_CAPTURE_SCRIPT)

    def _inject_all_open_pages(self) -> None:
        for page in self._iter_all_pages():
            try:
                self._inject_capture_script(page.playwright_page)
            except Exception:
                log.debug("HITL capture inject failed for page %s", page.page_id, exc_info=True)

    def _detach_nav_handler(self, page_id: int | None = None) -> None:
        if page_id is None:
            for tracked_page_id in list(self._nav_handlers):
                self._detach_nav_handler(tracked_page_id)
            return

        handler = self._nav_handlers.pop(page_id, None)
        if handler is None:
            return
        try:
            page = self._context.browser_context.get_page(page_id)
            page.playwright_page.remove_listener("framenavigated", handler)
        except Exception:
            log.debug("Failed to remove HITL navigation listener for page %s", page_id, exc_info=True)

    def _ensure_page_recording(self, page) -> None:
        playwright_page = page.playwright_page
        page_id = page.page_id

        self._ensure_context_setup(playwright_page)
        self._inject_capture_script(playwright_page)

        if page_id not in self._nav_handlers:
            def _on_navigate(frame) -> None:
                if frame != playwright_page.main_frame:
                    return
                url = frame.url
                try:
                    self._inject_capture_script(playwright_page)
                except Exception:
                    log.debug("HITL capture re-inject after navigation failed", exc_info=True)
                if not url or url == self._last_url:
                    return
                self._last_url = url
                self._record_navigation(url)

            playwright_page.on("framenavigated", _on_navigate)
            self._nav_handlers[page_id] = _on_navigate

        self._active_page_id = page_id

    def ensure_current_page(self) -> None:
        """Re-attach capture to the active tab if the human switched pages."""
        if not self._active:
            return
        try:
            page = self._context.browser_context.get_current_page()
        except Exception:
            return
        self._ensure_page_recording(page)

    def flush_pending_inputs(self) -> None:
        if not self._active:
            return
        for page in self._iter_all_pages():
            try:
                page.playwright_page.evaluate(_FLUSH_PENDING_INPUTS_SCRIPT)
            except Exception:
                log.debug(
                    "HITL pending-input flush failed for page %s",
                    page.page_id,
                    exc_info=True,
                )

    def clear_recorded(self) -> None:
        with self._lock:
            self._recorded.clear()

    def start(self) -> None:
        page = self._context.browser_context.get_current_page()
        self._last_url = page.url()

        if self._active:
            self.ensure_current_page()
            return

        self._recorded.clear()
        self._ensure_page_recording(page)
        self._inject_all_open_pages()
        self._active = True

    def stop(self, *, finalize: bool = True) -> list[tuple[str, dict[str, Any], ActionResult]]:
        if not self._active:
            return list(self._recorded)

        self._detach_nav_handler()
        self._active = False
        recorded = list(self._recorded)
        if finalize:
            self._recorded.clear()
            self._active_page_id = None
        return recorded

    def _record_navigation(self, url: str) -> None:
        action_name = "go_to_url"
        args = {"url": url}
        result = ActionResult(
            success=True,
            extracted_content=f"Human navigated to {url}",
            include_in_memory=True,
            action_name=action_name,
        )
        self._append_record(action_name, args, result)

    def _handle_capture_event(self, payload: dict[str, Any]) -> None:
        if not self._active:
            return
        with self._lock:
            event_type = payload.get("eventType", "")
            if event_type == "click":
                self._record_click(payload)
            elif event_type == "input":
                self._record_input(payload)
            elif event_type == "select":
                self._record_select(payload)
            elif event_type == "keydown":
                self._record_keys(payload)
            elif event_type == "scroll":
                self._record_scroll(payload)

    def _element_label(self, payload: dict[str, Any]) -> str:
        label = str(payload.get("label", "") or "").strip()
        if label:
            return label[:120]
        attrs = dict(payload.get("attributes") or {})
        for key in ("aria-label", "title", "placeholder", "name", "alt"):
            value = str(attrs.get(key, "") or "").strip()
            if value:
                return value[:120]
        return ""

    def _element_from_payload(self, payload: dict[str, Any]) -> DOMHistoryElement:
        accessible_name = self._element_label(payload) or None
        nested = str(payload.get("nestedIdentity") or payload.get("nested_identity") or "").strip() or None
        element = DOMHistoryElement(
            tag_name=payload.get("tagName", ""),
            xpath=payload.get("xpath", ""),
            highlight_index=None,
            attributes=dict(payload.get("attributes") or {}),
            accessible_name=accessible_name,
            frame_path=list(payload.get("framePath") or payload.get("frame_path") or []),
            stable_root=str(payload.get("stableRoot") or payload.get("stable_root") or "").strip() or None,
            relative_xpath=str(payload.get("relativeXPath") or payload.get("relative_xpath") or "").strip() or None,
            nested_identity=nested,
        )
        css_selector = enhanced_css_selector_for_history_element(element)
        if css_selector:
            element.css_selector = css_selector
        element.locator_chain = _locator_chain_from_hitl_element(element, payload)
        counted = next(
            (item for item in element.locator_chain if item.get("kind") in {"nth", "first", "last"}),
            None,
        )
        if counted:
            element.duplicate_set = {
                key: value for key, value in counted.items() if key != "kind"
            }
            element.duplicate_set["position"] = counted["kind"]
        return element

    def _dom_action_args(self, element: DOMHistoryElement, **extra: Any) -> dict[str, Any]:
        args: dict[str, Any] = {"xpath": element.xpath, **extra}
        if element.css_selector:
            args["css_selector"] = element.css_selector
        return args

    @staticmethod
    def _ordinal(index: int) -> str:
        if 10 <= index % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(index % 10, "th")
        return f"{index}{suffix}"

    @staticmethod
    def _role_phrase(tag: str, attrs: dict[str, Any], input_type: str) -> str:
        role = str(attrs.get("role") or "").strip().lower()
        itype = (input_type or str(attrs.get("type") or "")).strip().lower()
        if itype == "password":
            return "password field"
        if itype in {"email", "tel", "search", "url", "number"}:
            return f"{itype} field"
        if tag in {"input", "textarea"} or role == "textbox":
            return "text field"
        if itype == "submit" or (tag == "button" and itype == "submit"):
            return "submit button"
        if tag == "button" or role == "button" or itype in {"button", "reset"}:
            return "button"
        if tag == "a" or role == "link":
            return "link"
        if tag == "select" or role == "combobox":
            return "dropdown"
        if role in {"checkbox", "radio", "tab", "menuitem"}:
            return role
        return tag or "element"

    @classmethod
    def _page_region(cls, payload: dict[str, Any]) -> str:
        spatial = payload.get("spatial") if isinstance(payload.get("spatial"), dict) else {}
        return str(spatial.get("region") or "").strip().replace("_", "-")

    @classmethod
    def _spatial_suffix(cls, payload: dict[str, Any], tag: str) -> str:
        parts: list[str] = []
        nth = payload.get("nth") if isinstance(payload.get("nth"), dict) else {}
        index = nth.get("index")
        count = nth.get("count")
        kind = str(nth.get("kind") or nth.get("position") or "")
        noun = tag if tag else "item"
        if isinstance(count, int) and count >= 2 and isinstance(index, int) and index >= 1:
            if kind == "first":
                parts.append(f"first of {count} {noun}s")
            elif kind == "last":
                parts.append(f"last of {count} {noun}s")
            else:
                parts.append(f"{cls._ordinal(index)} of {count} {noun}s")
        region = cls._page_region(payload)
        if region:
            parts.append(region)
        return ", ".join(parts)

    _LANDMARK_RELATIONS = {
        "left": "left of",
        "right": "right of",
        "above": "above",
        "below": "below",
    }
    _LANDMARK_MAX_CHARS = 48
    _LANDMARK_MAX_WORDS = 6

    @classmethod
    def _is_coherent_phrase(cls, text: str) -> bool:
        value = " ".join(str(text or "").split())
        if not value or len(value) > cls._LANDMARK_MAX_CHARS:
            return False
        words = value.split()
        if len(words) > cls._LANDMARK_MAX_WORDS:
            return False
        numeric = sum(1 for word in words if word.isdigit() and len(word) <= 4)
        return numeric < 3

    @classmethod
    def _qualified_landmark(cls, payload: dict[str, Any]) -> tuple[str, str]:
        nearby = str(payload.get("nearbyText") or "").strip()
        relation = str(payload.get("nearbyRelation") or "").strip().lower()
        if cls._is_coherent_phrase(nearby) and relation in cls._LANDMARK_RELATIONS:
            return nearby, relation
        nth = payload.get("nth") if isinstance(payload.get("nth"), dict) else {}
        for name_key, relation_key in (("prevName", "prevRelation"), ("nextName", "nextRelation")):
            name = str(nth.get(name_key) or "").strip()
            peer_relation = str(nth.get(relation_key) or "").strip().lower()
            if cls._is_coherent_phrase(name) and peer_relation in cls._LANDMARK_RELATIONS:
                return name, peer_relation
        return "", ""

    @classmethod
    def describe_target(
        cls,
        payload: dict[str, Any],
        element: DOMHistoryElement | None = None,
    ) -> str:
        """Human-readable target for task text. Does not change locators."""
        attrs: dict[str, Any] = {}
        if element is not None:
            attrs.update(element.attributes or {})
        attrs.update(dict(payload.get("attributes") or {}))
        tag = str(
            payload.get("tagName") or getattr(element, "tag_name", "") or "element"
        ).lower()
        input_type = str(payload.get("inputType") or attrs.get("type") or "")
        role_phrase = cls._role_phrase(tag, attrs, input_type)
        visible = str(payload.get("label") or "").strip()
        aria = str(attrs.get("aria-label") or "").strip()
        placeholder = str(attrs.get("placeholder") or "").strip()
        name = str(attrs.get("name") or "").strip()
        associated = str(payload.get("associatedLabel") or "").strip()
        nested = str(
            payload.get("nestedIdentity")
            or getattr(element, "nested_identity", "")
            or ""
        ).strip()
        identity = visible or aria or placeholder or name or associated
        if identity:
            return identity
        landmark, relation = cls._qualified_landmark(payload)
        if landmark:
            return f"{role_phrase} {cls._LANDMARK_RELATIONS[relation]} {landmark!r}"
        if nested:
            return nested
        spatial = cls._spatial_suffix(payload, tag)
        if spatial:
            return f"{role_phrase} ({spatial})"
        return role_phrase

    @staticmethod
    def _attach_page(result: ActionResult, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "").strip()
        title = str(payload.get("title") or "").strip()
        result.page_url = url or None
        result.page_title = title or None

    def _append_record(
        self,
        action_name: str,
        args: dict[str, Any],
        result: ActionResult,
        element: DOMHistoryElement | None = None,
    ) -> None:
        if element is not None:
            result.interacted_element = element
        result.action_name = action_name
        result.action_index = len(self._recorded) + 1
        self._recorded.append((action_name, args, result))
        if self._on_action:
            try:
                self._on_action(result, action_name, args)
            except Exception:
                log.debug("HITL on_action callback failed", exc_info=True)

    def _record_click(self, payload: dict[str, Any]) -> None:
        element = self._element_from_payload(payload)
        label = self._element_label(payload)
        args = self._dom_action_args(element, **({"label": label} if label else {}))
        target = self.describe_target(payload, element)
        result = ActionResult(
            success=True,
            extracted_content=f"Human clicked {target}",
            include_in_memory=True,
            action_name="click_element",
            interacted_element=element,
        )
        self._attach_page(result, payload)
        self._append_record("click_element", args, result, element)

    def _record_input(self, payload: dict[str, Any]) -> None:
        element = self._element_from_payload(payload)
        text = str(payload.get("text", ""))
        label = self._element_label(payload)
        extra: dict[str, Any] = {"text": text}
        if label:
            extra["label"] = label
        args = self._dom_action_args(element, **extra)
        target = self.describe_target(payload, element)
        if text:
            extracted_content = f"Human entered {text!r} in {target}"
        else:
            extracted_content = f"Human entered text in {target}"
        result = ActionResult(
            success=True,
            extracted_content=extracted_content,
            include_in_memory=True,
            action_name="input_text",
            interacted_element=element,
        )
        self._attach_page(result, payload)
        self._append_record("input_text", args, result, element)

    def _record_select(self, payload: dict[str, Any]) -> None:
        element = self._element_from_payload(payload)
        text = str(payload.get("text", ""))
        label = self._element_label(payload)
        extra: dict[str, Any] = {"text": text}
        if label:
            extra["label"] = label
        args = self._dom_action_args(element, **extra)
        target = self.describe_target(payload, element)
        if text:
            extracted_content = f"Human selected {text!r} on {target}"
        else:
            extracted_content = f"Human selected option on {target}"
        result = ActionResult(
            success=True,
            extracted_content=extracted_content,
            include_in_memory=True,
            action_name="select_dropdown_option",
            interacted_element=element,
        )
        self._attach_page(result, payload)
        self._append_record("select_dropdown_option", args, result, element)

    def _record_keys(self, payload: dict[str, Any]) -> None:
        keys = str(payload.get("keys", ""))
        if not keys:
            return
        args = {"keys": keys}
        result = ActionResult(
            success=True,
            extracted_content=f"Human sent keys: {keys}",
            include_in_memory=True,
            action_name="send_keys",
        )
        self._attach_page(result, payload)
        self._append_record("send_keys", args, result)

    def _record_scroll(self, payload: dict[str, Any]) -> None:
        try:
            percent = int(payload.get("percent", 0))
        except (TypeError, ValueError):
            percent = 0
        percent = max(0, min(100, percent))
        scroll_kind = str(payload.get("scrollKind", "window") or "window")
        element: DOMHistoryElement | None = None
        if scroll_kind == "element":
            element = self._element_from_payload(payload)
            xpath = (element.xpath or "").strip()
            # Treat empty/root document paths as window scroll.
            if not xpath or xpath in {"html", "/html", "html[1]", "/html[1]"}:
                element = None
                args = {"yPercent": percent, "percent": percent}
            else:
                args = self._dom_action_args(element, yPercent=percent, percent=percent)
        else:
            args = {"yPercent": percent, "percent": percent}

        def make_scroll_result() -> ActionResult:
            scroll_result = ActionResult(
                success=True,
                extracted_content=f"Human scrolled to {percent}%",
                include_in_memory=True,
                action_name="scroll_to_percent",
                interacted_element=element,
            )
            self._attach_page(scroll_result, payload)
            return scroll_result

        # Coalesce consecutive scrolls on the same container into the latest percent.
        if self._recorded:
            last_name, last_args, _last_result = self._recorded[-1]
            if last_name == "scroll_to_percent":
                same_target = last_args.get("xpath") == args.get("xpath") and last_args.get(
                    "css_selector"
                ) == args.get("css_selector")
                if same_target:
                    if int(last_args.get("percent", last_args.get("yPercent", -1))) == percent:
                        return
                    result = make_scroll_result()
                    result.action_index = len(self._recorded)
                    self._recorded[-1] = ("scroll_to_percent", args, result)
                    if self._on_action:
                        try:
                            self._on_action(result, "scroll_to_percent", args)
                        except Exception:
                            log.debug("HITL on_action callback failed", exc_info=True)
                    return

        result = make_scroll_result()
        self._append_record("scroll_to_percent", args, result, element)


class HitlController:
    """Coordinates human-in-the-loop pause, recording, and resume."""

    def __init__(
        self,
        context: AgentContext,
        *,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ):
        self._context = context
        self._emit = emit or (lambda _event: None)
        self._recorder = HumanActionRecorder(context, on_action=self._on_human_action)
        self._command_queue: queue.Queue[_HitlCommand] = queue.Queue()
        self._intervention_cycle = 0
        self._session_start_url = ""
        self._session_start_title = ""

    def submit_command(
        self,
        action: str,
        *,
        timeout: float = 60.0,
        wait: bool = True,
        **kwargs: Any,
    ) -> tuple[bool, str | None]:
        """Queue a HITL command for execution on the browser/executor thread."""
        if action == "take_control":
            self._context.hitl_interrupt = True
            self._emit({"type": "take_control_pending"})
        command = _HitlCommand(action=action, kwargs=kwargs)
        self._command_queue.put(command)
        if not wait:
            return True, None
        if not command.done.wait(timeout):
            command.cancelled = True
            if action == "take_control":
                self._context.hitl_interrupt = False
            return False, f"HITL command '{action}' timed out"
        return command.ok, command.error

    def process_pending_commands(self) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except queue.Empty:
                break
            if command.cancelled:
                command.done.set()
                continue
            try:
                if command.action == "take_control":
                    command.ok = self.take_control(**command.kwargs)
                    if not command.ok:
                        command.error = "Failed to take control"
                elif command.action == "return_control":
                    command.ok = self.return_control()
                    if not command.ok:
                        command.error = "Failed to return control"
                elif command.action == "finish_manual":
                    command.ok = self.finish_manual()
                    if not command.ok:
                        command.error = "Failed to finish demonstration"
                else:
                    command.error = f"Unknown HITL command: {command.action}"
            except Exception as exc:
                command.ok = False
                command.error = str(exc)
                log.exception("HITL command %s failed", command.action)
            finally:
                if command.action == "take_control":
                    self._context.hitl_interrupt = False
                command.done.set()

        if self._context.human_controlling:
            try:
                self._recorder.ensure_current_page()
            except Exception:
                log.debug("HITL ensure_current_page failed", exc_info=True)

    def _run_prefix(self) -> str:
        run_id = self._context.run_id
        if run_id:
            return f"[run:{run_id[:8]}] "
        return ""

    @property
    def recorder(self) -> HumanActionRecorder:
        return self._recorder

    def set_enabled(self, enabled: bool) -> None:
        self._context.hitl_enabled = enabled

    def request_intervention(self, reason: str, *, source: str = "auto") -> bool:
        context = self._context
        if not context.hitl_enabled:
            return False
        if context.awaiting_human:
            context.hitl_reason = reason or context.hitl_reason
            context.hitl_source = source or context.hitl_source
            if not context.manual_mode:
                context.hitl_deadline = time.time() + context.options.hitl_timeout_seconds
            return True

        context.pause()
        context.awaiting_human = True
        context.hitl_reason = reason
        context.hitl_source = source
        if context.manual_mode:
            context.hitl_deadline = None
        else:
            context.hitl_deadline = time.time() + context.options.hitl_timeout_seconds
        self._intervention_cycle += 1

        self._emit(
            {
                "type": "human_intervention_required",
                "reason": reason,
                "deadline": context.hitl_deadline,
                "source": source,
                "cycle": self._intervention_cycle,
            }
        )
        self._emit({"type": "status", "status": "awaiting_human"})
        return True

    def take_control(self, *, source: str = "manual") -> bool:
        context = self._context
        if not context.hitl_enabled:
            return False
        if context.human_controlling:
            if not self._recorder.is_active:
                self._recorder.start()
            return True
        if not context.awaiting_human:
            reason = (
                "Demonstrate the test in the browser"
                if context.manual_mode
                else "Manual take control"
            )
            self.request_intervention(reason, source=source)
        try:
            page = context.browser_context.get_current_page()
            self._session_start_url = page.url()
            self._session_start_title = page.title()
        except Exception:
            self._session_start_url = ""
            self._session_start_title = ""
        context.human_controlling = True
        context.hitl_interrupt = False
        self._recorder.start()
        log.info(
            "%sHITL take_control reason=%s url=%s source=%s",
            self._run_prefix(),
            context.hitl_reason,
            self._session_start_url,
            source,
        )
        self._emit({"type": "human_control_started", "source": source})
        return True

    def return_control(self) -> bool:
        context = self._context
        if not context.human_controlling and not context.awaiting_human:
            return True

        recorded = self._capture_and_flush_recorded(set_handoff=True)
        log.info(
            "%sHITL release actions_recorded=%d",
            self._run_prefix(),
            len(recorded),
        )

        context.message_manager.prepare_post_hitl_resume()
        context.action_results.clear()
        context.human_controlling = False
        context.awaiting_human = False
        context.hitl_reason = ""
        context.hitl_deadline = None
        context.force_replan_after_hitl = True
        context.post_hitl_fresh_start = True
        context.hitl_interrupt = False
        context.stuck_episode_active = False
        context.stuck_recovery_attempts = 0
        context.critic_runs_this_episode = 0
        context.consecutive_unvalidated_done = 0
        context.awaiting_done_recovery = False
        context.consecutive_no_action_steps = 0
        context.resume()

        self._emit({"type": "human_intervention_ended", "cycle": self._intervention_cycle})
        self._emit({"type": "status", "status": "running"})
        return True

    def finish_manual(self) -> bool:
        context = self._context
        if not context.manual_mode:
            return False
        recorded = self._capture_and_flush_recorded(set_handoff=False)
        log.info(
            "%sHITL finish_manual actions_recorded=%d",
            self._run_prefix(),
            len(recorded),
        )
        context.human_controlling = False
        context.awaiting_human = False
        context.hitl_reason = ""
        context.hitl_deadline = None
        context.hitl_interrupt = False
        context.manual_finished = True
        context.resume()
        self._emit({"type": "human_intervention_ended", "cycle": self._intervention_cycle})
        self._emit({"type": "status", "status": "running"})
        return True

    def check_timeout(self) -> bool:
        context = self._context
        if context.manual_mode:
            return False
        if not context.awaiting_human:
            return False
        if context.hitl_deadline is None:
            return False
        if time.time() <= context.hitl_deadline:
            return False
        self._fail_timeout()
        return True

    def _fail_timeout(self) -> None:
        context = self._context
        if context.human_controlling:
            self.flush_recorded_to_history()
        context.human_controlling = False
        context.awaiting_human = False
        context.hitl_timed_out = True
        context.hitl_reason = "Human intervention timed out"
        context.stop()
        self._emit(
            {
                "type": "done",
                "status": "fail",
                "summary": "Human intervention timed out",
            }
        )

    def flush_recorded_to_history(self) -> bool:
        """Flush any buffered human actions into history (e.g. on cancel)."""
        context = self._context
        if not context.human_controlling and not self._recorder.is_active and not self._recorder.recorded:
            return False
        return bool(self._capture_and_flush_recorded(set_handoff=False))

    def _capture_and_flush_recorded(self, *, set_handoff: bool) -> list[tuple[str, dict[str, Any], ActionResult]]:
        context = self._context
        if self._recorder.is_active:
            self._recorder.flush_pending_inputs()
            recorded = self._recorder.stop(finalize=False)
        else:
            recorded = list(self._recorder.recorded)

        try:
            page = context.browser_context.get_current_page()
            end_url = page.url()
            end_title = page.title()
        except Exception:
            end_url = ""
            end_title = ""

        if set_handoff:
            context.pending_hitl_handoff = PendingHitlHandoff(
                recorded=recorded,
                intervention_reason=context.hitl_reason,
                intervention_source=context.hitl_source,
                cycle=self._intervention_cycle,
                start_url=self._session_start_url,
                start_title=self._session_start_title,
                end_url=end_url,
                end_title=end_title,
            )

        if not recorded:
            return []

        try:
            self._flush_to_history(recorded)
            self._recorder.clear_recorded()
            return recorded
        except Exception:
            log.exception("Failed to flush human actions to history")
            with self._recorder._lock:
                self._recorder._recorded[:] = recorded
            return recorded

    def _on_human_action(
        self,
        result: ActionResult,
        action_name: str,
        args: dict[str, Any],
    ) -> None:
        step_index = self._context.alloc_ui_step_index()
        self._emit(
            {
                "type": "human_action",
                "index": step_index,
                "action": action_name,
                "args": args,
                "result": result.extracted_content or "",
                "cycle": self._intervention_cycle,
            }
        )

    def _flush_to_history(
        self,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
    ) -> None:
        context = self._context
        page = context.browser_context.get_current_page()
        fallback_url = page.url()
        fallback_title = page.title()
        tabs = context.browser_context.get_tab_infos()

        for action_name, args, result in recorded:
            element = result.interacted_element
            interacted = [element] if element is not None else []
            record_url = result.page_url or fallback_url
            record_title = result.page_title or fallback_title
            model_output = json.dumps(
                {
                    "current_state": {
                        "evaluation_previous_goal": "Human",
                        "memory": "Human intervention",
                        "next_goal": action_name,
                    },
                    "action": [{action_name: args}],
                },
                ensure_ascii=False,
            )
            record = AgentStepRecord(
                model_output=model_output,
                result=[result],
                state=BrowserStateHistory(
                    url=record_url,
                    title=record_title,
                    tabs=tabs,
                    interacted_elements=interacted,
                ),
                metadata={"source": "human", "cycle": self._intervention_cycle},
            )
            context.history.history.append(record)

    @staticmethod
    def _redact_action_args(args: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(args)
        if "text" in redacted:
            redacted["text"] = "[redacted]"
        return redacted

    @classmethod
    def _format_human_action_line(
        cls,
        action_name: str,
        args: dict[str, Any],
        result: ActionResult,
        *,
        redact_sensitive: bool = False,
    ) -> str:
        display_args = cls._redact_action_args(args) if redact_sensitive else args
        summary = result.extracted_content or action_name
        details: list[str] = []
        if display_args.get("label"):
            details.append(f"label={display_args['label']!r}")
        if display_args.get("text"):
            details.append(f"text={display_args['text']!r}")
        if display_args.get("url"):
            details.append(f"url={display_args['url']!r}")
        if display_args.get("keys"):
            details.append(f"keys={display_args['keys']!r}")
        if display_args.get("percent") is not None or display_args.get("yPercent") is not None:
            pct = display_args.get("percent", display_args.get("yPercent"))
            details.append(f"percent={pct}")
        attrs = dict(display_args.get("attributes") or {})
        for key in ("aria-label", "title"):
            value = attrs.get(key)
            if value:
                details.append(f"{key}={value!r}")
        if display_args.get("xpath"):
            details.append(f"xpath={display_args['xpath']!r}")
        if details:
            return f"{summary} ({', '.join(details)})"
        return summary

    @classmethod
    def _format_action_trace_lines(
        cls,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
        *,
        redact_sensitive: bool = False,
    ) -> list[str]:
        return [
            f"- {cls._format_human_action_line(action_name, args, result, redact_sensitive=redact_sensitive)}"
            for action_name, args, result in recorded
        ]

    @staticmethod
    def _should_include_remaining_work(analysis: dict[str, Any] | None) -> bool:
        if not analysis:
            return False
        confidence = str(analysis.get("confidence", "") or "").strip().lower()
        outcome = str(analysis.get("outcome", "") or "").strip().lower()
        if confidence in {"", "low"} or outcome in {"", "unclear"}:
            return False
        return bool(str(analysis.get("remaining_work", "") or "").strip())

    @classmethod
    def format_human_memory_message(
        cls,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
        *,
        intervention_reason: str = "",
        intervention_source: str = "",
        analysis: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            "Human intervention handoff. Treat the current page state as authoritative "
            "and avoid repeating completed human steps unless the page changed."
        ]
        if intervention_source:
            lines.append(f"Intervention source: {intervention_source}")
        if intervention_reason:
            lines.append(f"Trigger context: {intervention_reason}")
        if analysis:
            for key, label in (
                ("inferred_reason", "Inferred reason"),
                ("goal_achieved", "Goal achieved"),
                ("outcome", "Outcome"),
                ("evidence", "Evidence"),
                ("confidence", "Confidence"),
            ):
                value = str(analysis.get(key, "") or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
            if cls._should_include_remaining_work(analysis):
                remaining_work = str(analysis.get("remaining_work", "") or "").strip()
                if remaining_work:
                    lines.append(f"Remaining work: {remaining_work}")
            elif str(analysis.get("confidence", "") or "").strip().lower() in {"", "low"} or str(
                analysis.get("outcome", "") or ""
            ).strip().lower() in {"", "unclear"}:
                lines.append(
                    "Guidance: Continue from the current page; do not undo human navigation."
                )
        if recorded:
            lines.append("Human action trace:")
            lines.extend(
                cls._format_action_trace_lines(recorded, redact_sensitive=bool(analysis))
            )
        return "\n".join(lines)

    def inject_human_memory(
        self,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
        *,
        intervention_reason: str = "",
        intervention_source: str = "",
        analysis: dict[str, Any] | None = None,
    ) -> None:
        message = self.format_human_memory_message(
            recorded,
            intervention_reason=intervention_reason,
            intervention_source=intervention_source,
            analysis=analysis,
        )
        self._context.message_manager.add_message_with_tokens(
            {"role": "user", "content": message},
            "hitl_handoff",
        )
