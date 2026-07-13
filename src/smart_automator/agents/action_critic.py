from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ..agent.messages.utils import coerce_navigator_response, preview_text
from .base import BaseAgent
from ..llm.base import BaseLLM

log = logging.getLogger(__name__)

ACTION_CRITIC_SYSTEM_PROMPT = """You are a one-shot action critic for a browser automation agent.

The navigator is stuck. Review the conversation and page state, then output ONLY flat JSON with the single most obvious missing action(s):

{"action": [{"click_element": {"index": N, "intent": "..."}}]}

Rules:
- Prefer one confirm/submit click when Enter/OK/Submit is visible after PIN or form entry.
- For incomplete PIN keypads, list each remaining digit click plus Enter if needed (max 5 actions).
- Use only indexed elements from the current page state.
- No AgentOutput wrapper, no tool-call envelopes, no commentary outside JSON.
"""

if TYPE_CHECKING:
    from ..agent.messages.service import MessageManager


class ActionCriticAgent(BaseAgent):
    def __init__(
        self,
        llm: BaseLLM,
        message_manager: MessageManager,
    ):
        super().__init__(
            llm,
            ACTION_CRITIC_SYSTEM_PROMPT,
            message_manager=message_manager,
            agent_id="action_critic",
        )

    def suggest_actions(self, reason: str) -> dict | None:
        messages = self._get_messages()
        critic_messages = [
            {"role": "system", "content": ACTION_CRITIC_SYSTEM_PROMPT},
            *messages[1:],
            {
                "role": "user",
                "content": (
                    f"Stuck reason: {reason}\n"
                    "What action(s) are missing? Output flat JSON with an action array only."
                ),
            },
        ]
        try:
            response, raw = self.get_json_response_with_raw(critic_messages, temperature=0.2)
            response = coerce_navigator_response(response)
            actions = response.get("action", [])
            if isinstance(actions, dict):
                actions = [actions]
            if not actions:
                return None
            return {
                "actions": actions,
                "raw_preview": preview_text(raw),
            }
        except Exception as error:
            log.warning("Action critic failed: %s", error)
            return {
                "error": str(error),
                "actions": [],
                "raw_preview": "",
            }

    @staticmethod
    def format_critic_hint(suggestion: dict) -> str:
        if suggestion.get("error"):
            return (
                "Action critic could not produce suggestions: "
                f"{suggestion['error']}"
            )
        actions_json = json.dumps(suggestion.get("actions", []), ensure_ascii=False)
        lines = [
            "Action critic suggestion (execute on the next navigator step):",
            actions_json,
            "Use these indexed actions if they match visible controls.",
        ]
        if suggestion.get("raw_preview"):
            lines.append(f"Critic raw preview: {suggestion['raw_preview']}")
        return "\n".join(lines)
