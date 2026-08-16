from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from ..agent.findings import (
    ScreenExcerpt,
    capture_screen_excerpt,
    format_excerpts_for_checker,
    missing_historical_excerpts_note,
)
from ..utils.prompts import build_browser_state_message
from .base import BaseAgent
from .output_schemas import validate_criteria_output
from ..llm.base import BaseLLM

if TYPE_CHECKING:
    from ..agent.context import AgentContext

log = logging.getLogger(__name__)

# Verification budgets — higher than navigator action observation (80 / 12k).
CRITERIA_MAX_OBSERVATION_ELEMENTS = 200
CRITERIA_MAX_OBSERVATION_CHARS = 24000
CRITERIA_MAX_ACCESSIBLE_NAMES = 200
CRITERIA_MAX_ACCESSIBLE_CHARS = 12000

CRITERIA_CHECKER_SYSTEM_PROMPT = """You are a test criteria evaluator for browser QA automation.

Review the task, success criteria, current browser state, earlier screen copy, and any completion notes.
Output ONLY valid JSON:

{"passed": true, "evidence": "what you observed on the page", "reason": "why passed or failed"}

Rules:
- Judge ONLY against the success criteria, not the task instructions alone.
- The CURRENT page is ground truth for what is true now.
- Earlier screens are recorded page copy and the only allowed evidence for what was true then.
- Short labels and values are kept as seen; lines marked [summarized] are condensed huge paragraphs — still use any values they retain.
- If a criterion compares a current value to an earlier value, compare the current page against earlier screens.
- If a criterion needs a past value, no earlier screen copy contains it, and that past value is not clearly on the CURRENT page, passed=false.
- Do not use completion notes, navigator memory, or assumptions as the past value.
- Use interactive elements, visible text, AND accessible names as evidence of page content.
- passed=true only when the success criteria are clearly fulfilled.
- passed=false when criteria are unmet, ambiguous, or contradicted.
- No commentary outside JSON.
"""


class CriteriaCheckerAgent(BaseAgent):
    def __init__(self, llm: BaseLLM):
        super().__init__(llm, CRITERIA_CHECKER_SYSTEM_PROMPT, agent_id="criteria_checker")

    def check(
        self,
        *,
        task: str,
        success_criteria: str,
        state_message: str,
        final_answer: str = "",
        test_name: str | None = None,
        excerpts: list[ScreenExcerpt] | None = None,
        referential: bool = False,
    ) -> dict:
        recorded = list(excerpts or [])
        user_parts = []
        if test_name and test_name.strip():
            user_parts.append(f"Test name: {test_name.strip()}")
        user_parts.append(f"Task: {task.strip()}")
        user_parts.append(f"Success criteria: {success_criteria.strip()}")
        if final_answer.strip():
            user_parts.append(f"Completion notes: {final_answer.strip()}")
        excerpts_block = format_excerpts_for_checker(recorded)
        if excerpts_block:
            user_parts.append(excerpts_block)
        missing_note = missing_historical_excerpts_note(
            referential=referential,
            excerpts=recorded,
        )
        if missing_note:
            user_parts.append(missing_note)
        if state_message.strip():
            user_parts.append(state_message.strip())
        user_parts.append(
            "Do the current page state and earlier screens satisfy the success criteria? "
            "Respond with JSON only."
        )

        messages = [
            {"role": "system", "content": CRITERIA_CHECKER_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        try:
            response = self.get_json_response(messages, temperature=0.1)
            return validate_criteria_output(response)
        except Exception as error:
            log.warning("Criteria checker failed: %s", error)
            return {
                "passed": False,
                "evidence": "",
                "reason": f"Criteria evaluation failed: {error}",
            }

    @classmethod
    def build_state_message(cls, context: "AgentContext") -> str:
        try:
            browser_state = context.browser_context.get_state(
                show_highlights=False,
                wait_for_stable=True,
            )
            message = build_browser_state_message(
                context,
                browser_state,
                include_action_results=False,
                max_elements=CRITERIA_MAX_OBSERVATION_ELEMENTS,
                max_chars=CRITERIA_MAX_OBSERVATION_CHARS,
                max_accessible_names=CRITERIA_MAX_ACCESSIBLE_NAMES,
                max_accessible_chars=CRITERIA_MAX_ACCESSIBLE_CHARS,
            )
            context.last_observation_text = message
            capture_screen_excerpt(
                context,
                message,
                url=browser_state.url,
                title=browser_state.title,
            )
            return message
        except Exception:
            return ""
