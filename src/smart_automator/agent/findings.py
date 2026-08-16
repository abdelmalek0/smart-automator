from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import AgentContext

MAX_EXCERPT_CHARS = 6000
LONG_PARAGRAPH_CHARS = 220
SUMMARY_LEAD_CHARS = 160

_REFERENTIAL_RE = re.compile(
    r"""
    \b(
        previously | earlier | before |
        steps?\s+ago |
        when\s+we |
        we\s+\w+ |
        same\s+as |
        matches? |
        equal(?:s|\s+to) |
        identical\s+to |
        shown\s+when |
        (?:from|on)\s+the\s+(?:previous|earlier|prior)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "do",
    "does", "for", "from", "had", "has", "have", "if", "in", "into", "is",
    "it", "its", "of", "on", "or", "our", "same", "should", "than", "that",
    "the", "then", "this", "to", "was", "we", "were", "when", "which", "with",
    "must", "page", "current", "visible", "shown", "displayed", "true",
    "success", "criteria", "equal", "equals", "matches", "match", "identical",
})

_DATUM_RE = re.compile(
    r"""
    (?:[$€£¥]\s*)\d{1,3}(?:,\d{3})*(?:\.\d+)?
    |
    \d{1,3}(?:,\d{3})+(?:\.\d+)?
    |
    \d+\.\d{2,}
    |
    \d+(?:\.\d+)?%
    |
    [A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}
    |
    (?<![A-Za-z])[A-Z]{2,5}[-_]?[A-Z0-9]{3,}\b
    |
    "[^"\n]{1,80}"
    |
    '[^'\n]{1,80}'
    """,
    re.VERBOSE,
)

_INDEX_LINE_RE = re.compile(r"^\[\d+\]")


@dataclass
class ScreenExcerpt:
    step: int
    url: str
    title: str
    text: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenExcerpt":
        return cls(
            step=int(data.get("step") or 0),
            url=str(data.get("url") or ""),
            title=str(data.get("title") or ""),
            text=str(data.get("text") or ""),
        )


def is_referential_criteria(criteria: str) -> bool:
    text = (criteria or "").strip()
    if not text:
        return False
    return bool(_REFERENTIAL_RE.search(text))


def criteria_retention_keywords(criteria: str) -> set[str]:
    return _keywords(criteria or "")


def format_capture_hint(referential: bool) -> str:
    if not referential:
        return ""
    return (
        "Earlier screen copy is recorded automatically for later criteria comparison. "
        "Do not call done until the current page shows the NOW side of any comparison."
    )


def format_excerpts_for_checker(excerpts: list[ScreenExcerpt]) -> str:
    if not excerpts:
        return ""
    parts = [
        "Earlier screens (page copy — the only allowed THEN evidence; "
        "huge paragraphs may be marked [summarized]; "
        "do not invent past values from memory or completion notes):"
    ]
    for excerpt in excerpts:
        title = excerpt.title.strip() or "(untitled)"
        parts.append(f"--- step {excerpt.step} | {title} | {excerpt.url} ---")
        parts.append(excerpt.text.strip())
    return "\n".join(parts)


def missing_historical_excerpts_note(
    *,
    referential: bool,
    excerpts: list[ScreenExcerpt],
) -> str:
    if not referential or excerpts:
        return ""
    return (
        "Earlier screens: none. If the success criteria require comparing "
        "to an earlier value that is not clearly visible on the CURRENT page, "
        "passed=false. Do not invent the past value from completion notes or memory."
    )


def clip_page_copy(
    observation: str,
    *,
    max_chars: int = MAX_EXCERPT_CHARS,
    keywords: set[str] | None = None,
) -> str:
    """Keep visible text and accessible names; condense huge paragraphs only."""
    visible = _section(observation, "Visible text")
    names = _section(observation, "Accessible names")
    parts: list[str] = []
    if visible:
        parts.append("[Visible text]")
        parts.append(_condense_long_paragraphs(visible, keywords or set()))
    if names:
        parts.append("[Accessible names]")
        parts.append(_condense_long_paragraphs(names, keywords or set()))
    clipped = "\n".join(parts).strip()
    if not clipped:
        clipped = _condense_long_paragraphs(_fallback_copy(observation), keywords or set())
    return _truncate(clipped, max_chars)


def capture_screen_excerpt(
    context: "AgentContext",
    observation: str,
    *,
    url: str,
    title: str = "",
) -> ScreenExcerpt | None:
    """Store a clip when referential criteria are set and the screen changed."""
    if not getattr(context, "referential_criteria", False):
        return None
    text = clip_page_copy(
        observation,
        keywords=set(getattr(context, "criteria_keywords", None) or []),
    )
    if not text.strip():
        return None

    step = 0
    if context.step_info is not None:
        step = int(context.step_info.step_number) + 1
    elif getattr(context, "n_steps", 0):
        step = int(context.n_steps)

    excerpt = ScreenExcerpt(
        step=step,
        url=(url or "").strip(),
        title=(title or "").strip(),
        text=text,
    )
    fingerprint = _fingerprint(excerpt)
    excerpts: list[ScreenExcerpt] = context.screen_excerpts
    if excerpts and _fingerprint(excerpts[-1]) == fingerprint:
        return None
    excerpts.append(excerpt)
    return excerpt


def _section(observation: str, heading: str) -> str:
    marker = f"[{heading}]"
    start = (observation or "").find(marker)
    if start < 0:
        return ""
    body = observation[start + len(marker) :]
    lines: list[str] = []
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped:
            if lines:
                lines.append("")
            continue
        if stripped.startswith("[") and stripped.endswith("]") and stripped != marker:
            break
        if stripped.startswith("Note:") and "not clickable" in stripped.lower():
            continue
        lines.append(raw.rstrip())
    return "\n".join(lines).strip()


def _condense_long_paragraphs(text: str, keywords: set[str]) -> str:
    """Leave short UI copy intact; summarize only huge paragraphs."""
    out: list[str] = []
    prose_run: list[str] = []

    def flush_prose() -> None:
        if not prose_run:
            return
        joined = " ".join(prose_run)
        if len(joined) > LONG_PARAGRAPH_CHARS:
            out.append(_summarize_paragraph(joined, keywords))
        else:
            out.extend(prose_run)
        prose_run.clear()

    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            flush_prose()
            if out and out[-1] != "":
                out.append("")
            continue
        if _is_prose_line(stripped):
            prose_run.append(stripped)
            continue
        flush_prose()
        out.append(stripped)
    flush_prose()
    return "\n".join(out).strip()


def _is_prose_line(line: str) -> bool:
    return len(line) > LONG_PARAGRAPH_CHARS or len(line.split()) >= 8


def _summarize_paragraph(paragraph: str, keywords: set[str]) -> str:
    datums = [match.group(0).strip() for match in _DATUM_RE.finditer(paragraph)]
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", paragraph.strip())
        if part.strip()
    ]
    kept: list[str] = []
    if sentences:
        kept.append(sentences[0][:SUMMARY_LEAD_CHARS].rstrip())
    for sentence in sentences[1:]:
        if _DATUM_RE.search(sentence) or (keywords and keywords & _keywords(sentence)):
            kept.append(sentence[:SUMMARY_LEAD_CHARS].rstrip())
        if len(kept) >= 3:
            break
    summary = " ".join(kept) if kept else paragraph[:SUMMARY_LEAD_CHARS].rstrip()
    extras = [datum for datum in dict.fromkeys(datums) if datum not in summary]
    if extras:
        summary = f"{summary} | {', '.join(extras)}"
    return f"[summarized] {summary}"


def _fallback_copy(observation: str) -> str:
    kept: list[str] = []
    for raw in (observation or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if _INDEX_LINE_RE.match(stripped):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if stripped.startswith("Current tab:") or stripped.startswith("Current step:"):
            continue
        kept.append(stripped)
    return "\n".join(kept)


def _truncate(text: str, max_chars: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 16].rstrip() + "\n... [truncated]"


def _fingerprint(excerpt: ScreenExcerpt) -> str:
    body = re.sub(r"\s+", " ", excerpt.text).strip().casefold()
    title = re.sub(r"\s+", " ", excerpt.title).strip().casefold()
    return f"{title}|{body}"


def _keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{2,}", (text or "").lower())
    return {token for token in tokens if token not in _STOPWORDS}
