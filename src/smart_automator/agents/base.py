from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..llm.base import BaseLLM
from ..agent.messages.utils import (
    convert_messages_for_chat,
    extract_json_from_model_output,
    fix_actions,
    normalize_model_json,
    remove_think_tags,
    validate_navigator_actions,
)
from .errors import ResponseParseError, classify_llm_error
from .output_schemas import validate_navigator_output

if TYPE_CHECKING:
    from ..agent.context import AgentContext
    from ..agent.messages.service import MessageManager


class BaseAgent:
    def __init__(
        self,
        llm: BaseLLM,
        system_prompt: str,
        message_manager: MessageManager | None = None,
        agent_id: str = "agent",
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._message_manager = message_manager
        self.id = agent_id
        self._standalone_messages: list[dict] = [{"role": "system", "content": system_prompt}]

    def _get_messages(self) -> list[dict]:
        if self._message_manager:
            return self._message_manager.get_messages()
        return self._standalone_messages

    def add_user_message(self, content: str):
        if self._message_manager:
            self._message_manager.add_message_with_tokens({"role": "user", "content": content})
        else:
            self._standalone_messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        if self._message_manager:
            self._message_manager.add_message_with_tokens({"role": "assistant", "content": content})
        else:
            self._standalone_messages.append({"role": "assistant", "content": content})

    def invoke(self, messages: list[dict] | None = None, temperature: float = 0.7) -> str:
        if self._message_manager:
            if self._llm.model_name:
                self._message_manager.settings.token_model = self._llm.model_name
            self._message_manager.cut_messages()
        msgs = messages if messages is not None else self._get_messages()
        chat_messages = convert_messages_for_chat(msgs)
        if self._llm.supports_structured_output:
            return self._llm.chat_json(chat_messages, temperature=temperature)
        return self._llm.chat(chat_messages, temperature=temperature)

    def get_json_response(self, messages: list[dict] | None = None, temperature: float = 0.7) -> dict:
        parsed, _ = self.get_json_response_with_raw(messages, temperature)
        return parsed

    def get_json_response_with_raw(
        self,
        messages: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> tuple[dict, str]:
        try:
            response = self.invoke(messages, temperature)
        except Exception as error:
            raise classify_llm_error(error) from error
        cleaned = remove_think_tags(response)
        try:
            parsed = extract_json_from_model_output(cleaned)
        except Exception as error:
            try:
                parsed = self._parse_json(cleaned)
            except Exception as inner_error:
                raise ResponseParseError(
                    f"Failed to parse model output: {error}",
                    inner_error,
                ) from inner_error
        normalized = normalize_model_json(parsed)
        if "action" in normalized or "actions" in normalized:
            fixed = fix_actions(normalized)
            normalized["action"] = validate_navigator_actions(fixed)
            normalized = validate_navigator_output(normalized)
        return normalized, response

    def _parse_json(self, text: str):
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            return {}

    def reset(self):
        self._standalone_messages = [{"role": "system", "content": self._system_prompt}]
