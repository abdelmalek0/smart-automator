from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from ..utils.prompts import build_browser_state_message
from .base import BaseAgent
from .output_schemas import validate_criteria_output
from ..llm.base import BaseLLM

if TYPE_CHECKING:
    from ..agent.context import AgentContext

log = logging.getLogger(__name__)

CRITERIA_CHECKER_SYSTEM_PROMPT = """You are a test criteria evaluator for browser QA automation.

Review the task, success criteria, current browser state, and any completion notes.
Output ONLY valid JSON:

{"passed": true, "evidence": "what you observed on the page", "reason": "why passed or failed"}

Rules:
- Judge ONLY against the success criteria, not the task instructions alone.
- Base your judgment on the CURRENT page state shown, not assumptions or memory.
- passed=true only when the success criteria are clearly fulfilled on the current page.
- passed=false when criteria are unmet, ambiguous, or contradicted by the page.
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
    ) -> dict:
        user_parts = []
        if test_name and test_name.strip():
            user_parts.append(f"Test name: {test_name.strip()}")
        user_parts.append(f"Task: {task.strip()}")
        user_parts.append(f"Success criteria: {success_criteria.strip()}")
        if final_answer.strip():
            user_parts.append(f"Completion notes: {final_answer.strip()}")
        if state_message.strip():
            user_parts.append(state_message.strip())
        user_parts.append(
            "Does the current page state satisfy the success criteria? "
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
                wait_for_stable=False,
            )
            return build_browser_state_message(context, browser_state)
        except Exception:
            return ""
