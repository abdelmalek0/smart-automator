from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..agent.context import PendingHitlHandoff
from ..agent.hitl import HitlController
from ..utils.prompts import build_browser_state_message
from .base import BaseAgent
from .output_schemas import validate_hitl_debrief_output
from ..llm.base import BaseLLM

if TYPE_CHECKING:
    from ..agent.context import AgentContext
    from ..agent.messages.service import MessageManager

log = logging.getLogger(__name__)

HITL_DEBRIEF_SYSTEM_PROMPT = """You analyze completed human browser interventions for a QA automation agent.

Review the task, trigger context, ordered human action trace, and CURRENT browser state.
Output ONLY valid JSON:

{
  "inferred_reason": "why the human likely intervened",
  "goal_achieved": "concise goal or state reached",
  "outcome": "achieved",
  "evidence": "action/page evidence supporting the conclusion",
  "remaining_work": "what the agent should do next",
  "confidence": "high"
}

Rules:
- outcome must be one of: achieved, partial, unclear, failed
- confidence must be one of: high, medium, low
- Infer intent only from the human action trace labels, URL/title transition, and current page state
- Do not infer goals from the task text or trigger context unless the action trace and page evidence support them
- For manual take-control, treat the trigger reason as weak context
- For agent-requested help, use the supplied reason as context but still verify against the action trace and current page
- If action labels are missing or evidence is weak (tag + xpath only), set outcome=unclear and confidence=low instead of guessing
- If evidence is insufficient, set outcome=unclear and confidence=low instead of guessing
- Do not reproduce passwords, PINs, or other sensitive typed values in the analysis
- Do not output browser actions; only analyze what happened
- No commentary outside JSON
"""


class HitlDebriefAgent(BaseAgent):
    def __init__(
        self,
        llm: BaseLLM,
        message_manager: MessageManager,
        context: "AgentContext | None" = None,
    ):
        super().__init__(
            llm,
            HITL_DEBRIEF_SYSTEM_PROMPT,
            message_manager=message_manager,
            agent_id="hitl_debrief",
        )
        self._context = context

    def _build_compact_messages(
        self,
        *,
        task: str,
        handoff: PendingHitlHandoff,
        state_message: str,
        success_criteria: str = "",
    ) -> list[dict]:
        action_lines = [
            f"- {HitlController._format_human_action_line(action_name, args, result)}"
            for action_name, args, result in handoff.recorded
        ]
        user_parts = [
            f"Task: {task.strip()}",
            f"Intervention source: {handoff.intervention_source or 'unknown'}",
            f"Trigger context: {handoff.intervention_reason or 'unknown'}",
            f"Intervention cycle: {handoff.cycle}",
            (
                "Page transition: "
                f"{handoff.start_url or 'unknown'} ({handoff.start_title or ''})"
                f" -> {handoff.end_url or 'unknown'} ({handoff.end_title or ''})"
            ),
            "Human action trace:\n" + ("\n".join(action_lines) if action_lines else "- none"),
        ]
        if success_criteria.strip():
            user_parts.append(f"Success criteria: {success_criteria.strip()}")
        if state_message.strip():
            user_parts.append(state_message.strip())
        user_parts.append(
            "Analyze what the human accomplished and what the agent should do next. "
            "Respond with JSON only."
        )
        return [
            {"role": "system", "content": HITL_DEBRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    def analyze(
        self,
        *,
        task: str,
        handoff: PendingHitlHandoff,
        success_criteria: str = "",
    ) -> dict[str, Any]:
        state_message = ""
        if self._context is not None:
            try:
                browser_state = self._context.browser_context.get_state(
                    show_highlights=False,
                    wait_for_stable=False,
                )
                state_message = build_browser_state_message(
                    self._context,
                    browser_state,
                    include_action_results=False,
                )
            except Exception:
                state_message = ""

        messages = self._build_compact_messages(
            task=task,
            handoff=handoff,
            state_message=state_message,
            success_criteria=success_criteria,
        )
        try:
            response = self.get_json_response(messages, temperature=0.2)
            return validate_hitl_debrief_output(response)
        except Exception as error:
            log.warning("HITL debrief failed: %s", error)
            return {
                "inferred_reason": handoff.intervention_reason or "Human intervention",
                "goal_achieved": "",
                "outcome": "unclear",
                "evidence": f"Debrief failed: {error}",
                "remaining_work": "Continue from the current page state.",
                "confidence": "low",
                "error": str(error),
            }

    @staticmethod
    def serialize_actions(
        handoff: PendingHitlHandoff,
    ) -> list[dict[str, Any]]:
        return [
            {
                "action": action_name,
                "args": dict(args),
                "result": result.extracted_content or "",
            }
            for action_name, args, result in handoff.recorded
        ]
