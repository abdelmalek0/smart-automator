from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ..agent.messages.utils import coerce_navigator_response, preview_text
from ..utils.prompts import build_browser_state_message
from .base import BaseAgent
from ..llm.base import BaseLLM

log = logging.getLogger(__name__)

ACTION_CRITIC_SYSTEM_PROMPT = """You are a one-shot action critic for a browser automation agent.

The navigator is stuck. Review the task, current page state, and stuck reason, then output ONLY flat JSON:

{"action": [{"click_element": {"index": N, "intent": "..."}}]}

Rules:
- Prefer one confirm/submit click when Enter/OK/Submit is visible after PIN or form entry.
- For incomplete PIN keypads, list each remaining digit click plus Enter if needed (max 5 actions).
- Use only indexed elements from the current page state.
- No AgentOutput wrapper, no tool-call envelopes, no commentary outside JSON.
"""

if TYPE_CHECKING:
    from ..agent.context import AgentContext
    from ..agent.messages.service import MessageManager


class ActionCriticAgent(BaseAgent):
    def __init__(
        self,
        llm: BaseLLM,
        message_manager: MessageManager,
        context: "AgentContext | None" = None,
    ):
        super().__init__(
            llm,
            ACTION_CRITIC_SYSTEM_PROMPT,
            message_manager=message_manager,
            agent_id="action_critic",
        )
        self._context = context

    def _build_compact_messages(self, reason: str) -> list[dict]:
        history = self._message_manager.get_messages() if self._message_manager else []
        task_message = ""
        for message in history:
            if message.get("role") == "user":
                content = str(message.get("content", ""))
                if "<nano_user_request>" in content:
                    task_message = content
                    break

        state_message = ""
        if self._context and self._context.state_message_added:
            for message in reversed(history):
                if message.get("role") == "user" and "[Current state starts here]" in str(
                    message.get("content", "")
                ):
                    state_message = str(message.get("content", ""))
                    break
        elif self._context:
            try:
                browser_state = self._context.browser_context.get_state(
                    show_highlights=False,
                    wait_for_stable=False,
                )
                state_message = build_browser_state_message(self._context, browser_state)
            except Exception:
                state_message = ""

        recent_lines: list[str] = []
        for message in reversed(history[-6:]):
            role = message.get("role", "")
            content = str(message.get("content", ""))
            if role == "assistant" and content.startswith("{"):
                try:
                    parsed = json.loads(content)
                    state = parsed.get("current_state", {})
                    if state:
                        recent_lines.append(
                            f"navigator: {state.get('next_goal') or state.get('memory', '')}"[:160]
                        )
                except json.JSONDecodeError:
                    pass
            elif role == "user" and (
                content.startswith("Action error:")
                or content.startswith("Previously failed actions")
            ):
                recent_lines.append(content[:160])
            if len(recent_lines) >= 3:
                break

        user_parts = [f"Stuck reason: {reason}"]
        if task_message:
            user_parts.append(task_message)
        if state_message:
            user_parts.append(state_message)
        if recent_lines:
            user_parts.append("Recent issues:\n" + "\n".join(reversed(recent_lines)))
        user_parts.append(
            "What action(s) are missing? Output flat JSON with an action array only."
        )

        return [
            {"role": "system", "content": ACTION_CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    def suggest_actions(self, reason: str) -> dict | None:
        critic_messages = self._build_compact_messages(reason)
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
