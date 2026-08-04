"""Harvest accessible names from the live DOM for verification (criteria) observation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .page import Page

# Framework-agnostic: aria-label, role labels, Flutter flt-semantics, etc.
# Playwright page.evaluate accepts a single arg — pack limits as one object.
_COLLECT_ACCESSIBLE_NAMES_JS = """
({ maxNames, maxChars }) => {
  const ignoredRoles = new Set(['presentation', 'none', 'generic']);
  const seen = new Set();
  const labels = [];
  let totalChars = 0;
  const nodes = document.querySelectorAll(
    '[aria-label], [role], flt-semantics, [title]'
  );
  for (const el of nodes) {
    if (labels.length >= maxNames || totalChars >= maxChars) break;
    const style = window.getComputedStyle(el);
    if (
      style.visibility === 'hidden' ||
      style.display === 'none' ||
      style.opacity === '0'
    ) {
      continue;
    }
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 && rect.height <= 0) continue;

    let label = (el.getAttribute('aria-label') || '').trim();
    if (!label) {
      const role = (el.getAttribute('role') || '').trim().toLowerCase();
      if (!role || ignoredRoles.has(role)) continue;
      label = (el.getAttribute('title') || '').trim();
      if (!label) {
        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
        if (text && text.length <= 120) label = text;
      }
    }
    if (!label) continue;
    const key = label.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    labels.push(label);
    totalChars += label.length + 1;
  }
  return labels;
}
"""


def collect_accessible_names(
    page: "Page",
    *,
    max_names: int = 200,
    max_chars: int = 12000,
) -> list[str]:
    """Return unique visible accessible names from the current page."""
    try:
        result = page._evaluate_on_page(
            _COLLECT_ACCESSIBLE_NAMES_JS,
            {"maxNames": max_names, "maxChars": max_chars},
        )
    except Exception:
        return []
    if not isinstance(result, list):
        return []
    names: list[str] = []
    used = 0
    for item in result:
        text = str(item or "").strip()
        if not text:
            continue
        if used + len(text) > max_chars and names:
            break
        names.append(text)
        used += len(text) + 1
        if len(names) >= max_names:
            break
    return names


def format_accessible_names_section(names: list[str]) -> str:
    if not names:
        return ""
    body = "\n".join(names)
    return (
        "[Accessible names]\n"
        f"{body}\n"
        "Note: accessible names are read-only page labels for verification — not clickable.\n"
    )
