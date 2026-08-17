from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from ..agent.context import ActionResult
from .base import BaseAgent
from .output_schemas import validate_task_extractor_output
from ..llm.base import BaseLLM

if TYPE_CHECKING:
    from ..agent.context import AgentContext
    from ..agent.history import AgentStepHistory
    from ..agent.messages.service import MessageManager

log = logging.getLogger(__name__)

TASK_EXTRACTOR_SYSTEM_PROMPT = """You name a QA test from a completed human browser demonstration.

Output ONLY valid JSON:
{"name": "Short test name"}

Rules:
- name: 2-6 word title for what was demonstrated
- Do not write steps, locators, xpath, CSS, or success criteria
- No commentary outside JSON
"""

_GENERIC_NAMES = frozenset(
    {
        "",
        "human demonstration",
        "untitled",
        "untitled test",
    }
)

_IMPERATIVE_VERBS = {
    "click_element": "Click",
    "input_text": "Type",
    "select_dropdown_option": "Select",
    "scroll_to_percent": "Scroll to",
    "send_keys": "Press",
    "go_to_url": "Go to",
    "open_url": "Go to",
}

# Longer prefixes first so "entered text in" wins over "entered".
_NARRATION_PREFIXES = (
    ("human clicked ", "Click"),
    ("human entered text in ", "Type"),
    ("human entered ", "Type"),
    ("human selected option on ", "Select"),
    ("human selected ", "Select"),
    ("human scrolled to ", "Scroll to"),
    ("human navigated to ", "Go to"),
    ("human sent keys: ", "Press"),
    ("human sent keys ", "Press"),
)

_PAST_PREFIXES = (
    ("clicked ", "Click"),
    ("entered text in ", "Type"),
    ("entered ", "Type"),
    ("typed ", "Type"),
    ("selected option on ", "Select"),
    ("selected ", "Select"),
    ("scrolled to ", "Scroll to"),
    ("navigated to ", "Go to"),
    ("sent keys: ", "Press"),
    ("sent keys ", "Press"),
)


class TaskExtractorAgent(BaseAgent):
    def __init__(
        self,
        llm: BaseLLM,
        message_manager: "MessageManager | None" = None,
        context: "AgentContext | None" = None,
    ):
        super().__init__(
            llm,
            TASK_EXTRACTOR_SYSTEM_PROMPT,
            message_manager=message_manager,
            agent_id="task_extractor",
        )
        self._context = context

    @staticmethod
    def _page_of(record, result: ActionResult) -> tuple[str, str]:
        url = str(getattr(result, "page_url", None) or "").strip()
        title = str(getattr(result, "page_title", None) or "").strip()
        state = getattr(record, "state", None)
        if not url:
            url = str(getattr(state, "url", "") or "").strip()
        if not title:
            title = str(getattr(state, "title", "") or "").strip()
        return url, title

    @classmethod
    def _to_imperative(cls, action_name: str, summary: str) -> str:
        text = str(summary or "").strip()
        if not text:
            return _IMPERATIVE_VERBS.get(str(action_name or "").strip()) or ""
        inferred = ""
        lower = text.lower()
        for prefix, verb in _NARRATION_PREFIXES:
            if lower.startswith(prefix):
                text = text[len(prefix) :].strip()
                inferred = verb
                lower = text.lower()
                break
        for prefix, verb in _PAST_PREFIXES:
            if lower.startswith(prefix):
                text = text[len(prefix) :].strip()
                inferred = inferred or verb
                lower = text.lower()
                break
        verb = _IMPERATIVE_VERBS.get(str(action_name or "").strip()) or inferred
        if not verb:
            return text
        if lower == verb.lower():
            return verb
        if lower.startswith(verb.lower() + " "):
            text = text[len(verb) :].strip()
        return f"{verb} {text}".strip() if text else verb

    @classmethod
    def _extractor_action_line(
        cls,
        action_name: str,
        args: dict[str, Any],
        result: ActionResult,
    ) -> str:
        summary = str(result.extracted_content or "").strip()
        if action_name == "input_text":
            text = args.get("text")
            if text not in (None, "") and str(text) not in summary and repr(text) not in summary:
                summary = f"{summary} value={text!r}" if summary else f"Human entered {text!r}"
        if action_name == "select_dropdown_option":
            text = args.get("text")
            if text not in (None, "") and str(text) not in summary and repr(text) not in summary:
                summary = f"{summary} value={text!r}" if summary else f"Human selected {text!r}"
        return cls._to_imperative(action_name, summary or action_name)

    @classmethod
    def action_lines_from_history(cls, history: "AgentStepHistory") -> list[str]:
        lines: list[str] = []
        last_url = ""
        last_was_scroll = False
        for record in history.history:
            try:
                parsed = json.loads(record.model_output or "{}")
            except (TypeError, json.JSONDecodeError):
                parsed = {}
            actions = parsed.get("action") or []
            if isinstance(actions, dict):
                actions = [actions]
            result = record.result[0] if record.result else ActionResult()
            page_url, page_title = cls._page_of(record, result)
            emitted = False
            for item in actions:
                if not isinstance(item, dict) or not item:
                    continue
                name, args = next(iter(item.items()))
                if not isinstance(args, dict):
                    args = {}
                line = cls._extractor_action_line(str(name), args, result)
                if not line:
                    continue
                is_scroll = str(name) == "scroll_to_percent"
                if is_scroll and last_was_scroll and lines:
                    lines[-1] = line
                    last_was_scroll = True
                    emitted = True
                    continue
                if page_url and page_url != last_url:
                    page_bit = page_url
                    if page_title:
                        page_bit = f"{page_url} ({page_title})"
                    lines.append(f"On page: {page_bit}")
                    last_url = page_url
                lines.append(line)
                last_was_scroll = is_scroll
                emitted = True
            if not emitted:
                leftover = str(result.extracted_content or "").strip()
                if leftover:
                    action_name = str(getattr(result, "action_name", "") or "")
                    lines.append(cls._to_imperative(action_name, leftover))
                    last_was_scroll = False
        return lines

    @classmethod
    def task_from_action_lines(cls, action_lines: list[str]) -> str:
        steps = [
            cls._to_imperative("", line)
            for line in action_lines
            if line and not line.startswith("On page:")
        ]
        steps = [step for step in steps if step]
        if not steps:
            return "Complete the demonstrated browser flow."
        return "\n".join(f"{index}. {line}" for index, line in enumerate(steps, 1))

    @classmethod
    def _usable_name(cls, name: str, existing_name: str = "") -> str:
        cleaned = str(name or "").strip()
        if cleaned.lower() in _GENERIC_NAMES:
            return str(existing_name or "").strip()
        return cleaned

    def extract(
        self,
        *,
        action_lines: list[str],
        success_criteria: str = "",
        existing_name: str = "",
        start_url: str = "",
        end_url: str = "",
        start_title: str = "",
        end_title: str = "",
    ) -> dict[str, Any]:
        task = self.task_from_action_lines(action_lines)
        name = self._usable_name(existing_name)
        if name:
            return {"task": task, "name": name, "extractor_llm_ms": 0}

        user_parts = [
            (
                "Page transition: "
                f"{start_url or 'unknown'} ({start_title or ''})"
                f" -> {end_url or 'unknown'} ({end_title or ''})"
            ),
            "Human action trace:\n"
            + ("\n".join(f"- {line}" for line in action_lines) if action_lines else "- none"),
        ]
        if success_criteria.strip():
            user_parts.append(
                "Success criteria (context only, do not copy): " + success_criteria.strip()
            )
        user_parts.append("Name this demonstration as JSON only.")
        messages = [
            {"role": "system", "content": TASK_EXTRACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        llm_started = time.perf_counter()
        try:
            response = self.get_json_response(messages, temperature=0.0)
            result = validate_task_extractor_output(response)
            result["extractor_llm_ms"] = int((time.perf_counter() - llm_started) * 1000)
            result["task"] = task
            result["name"] = self._usable_name(result.get("name") or "", existing_name)
            return result
        except Exception as error:
            log.warning("Task name extractor failed: %s", error)
            return {
                "task": task,
                "name": existing_name.strip(),
                "error": str(error),
                "extractor_llm_ms": int((time.perf_counter() - llm_started) * 1000),
            }
