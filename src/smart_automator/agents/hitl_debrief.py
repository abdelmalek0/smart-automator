from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ..agent.context import PendingHitlHandoff
from ..agent.hitl import HitlController
from .base import BaseAgent
from .output_schemas import validate_hitl_debrief_output
from ..llm.base import BaseLLM

if TYPE_CHECKING:
    from ..agent.context import AgentContext
    from ..agent.messages.service import MessageManager

log = logging.getLogger(__name__)

MAX_DEBRIEF_ACTION_LINES = 20

HITL_DEBRIEF_SYSTEM_PROMPT = """You analyze completed human browser interventions for a QA automation agent.

Output ONLY valid JSON:
{
  "inferred_reason": "why the human likely intervened",
  "goal_achieved": "concise goal or state reached",
  "outcome": "achieved",
  "evidence": "action/page evidence supporting the conclusion",
  "remaining_work": "what the agent should do next from the current page only",
  "confidence": "high"
}

Rules:
- outcome: achieved | partial | unclear | failed
- confidence: high | medium | low
- Infer intent only from the human action trace labels and URL/title transition
- Do not infer goals from the task text or trigger context unless action evidence supports them
- remaining_work must describe forward progress from the current page only; do not name a different navigation target than the end page implies when evidence is weak
- If action labels are weak (tag + xpath only), set outcome=unclear and confidence=low and leave remaining_work empty
- Do not reproduce passwords or sensitive typed values
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

    @staticmethod
    def _page_identity_message(end_url: str, end_title: str) -> str:
        if end_url or end_title:
            return f"Current page: {end_url or 'unknown'} ({end_title or ''})"
        return ""

    def _build_compact_messages(
        self,
        *,
        task: str,
        handoff: PendingHitlHandoff,
        state_message: str,
        success_criteria: str = "",
    ) -> list[dict]:
        recorded = handoff.recorded[-MAX_DEBRIEF_ACTION_LINES:]
        action_lines = [
            f"- {HitlController._format_human_action_line(action_name, args, result)}"
            for action_name, args, result in recorded
        ]
        if len(handoff.recorded) > MAX_DEBRIEF_ACTION_LINES:
            action_lines.insert(
                0,
                f"- ... {len(handoff.recorded) - MAX_DEBRIEF_ACTION_LINES} earlier actions omitted",
            )
        user_parts = [
            f"Task: {task.strip()}",
            f"Intervention source: {handoff.intervention_source or 'unknown'}",
            f"Trigger context: {handoff.intervention_reason or 'unknown'}",
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
        state_message = self._page_identity_message(handoff.end_url, handoff.end_title)

        messages = self._build_compact_messages(
            task=task,
            handoff=handoff,
            state_message=state_message,
            success_criteria=success_criteria,
        )
        llm_started = time.perf_counter()
        try:
            response = self.get_json_response(messages, temperature=0.0)
            llm_ms = int((time.perf_counter() - llm_started) * 1000)
            result = validate_hitl_debrief_output(response)
            result["debrief_llm_ms"] = llm_ms
            result["debrief_get_state_ms"] = 0
            return result
        except Exception as error:
            llm_ms = int((time.perf_counter() - llm_started) * 1000)
            log.warning("HITL debrief failed after %sms: %s", llm_ms, error)
            return {
                "inferred_reason": handoff.intervention_reason or "Human intervention",
                "goal_achieved": "",
                "outcome": "unclear",
                "evidence": f"Debrief failed: {error}",
                "remaining_work": "Continue from the current page state.",
                "confidence": "low",
                "error": str(error),
                "debrief_llm_ms": llm_ms,
                "debrief_get_state_ms": 0,
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
