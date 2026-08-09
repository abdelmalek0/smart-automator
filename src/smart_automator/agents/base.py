from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from ..llm.base import BaseLLM
from ..agent.messages.utils import (
    convert_messages_for_chat,
    extract_json_from_model_output,
    fix_actions,
    normalize_model_json,
    preview_text,
    remove_think_tags,
    validate_navigator_actions,
)
from .errors import ResponseParseError, HitlInterruptedError, classify_llm_error
from ..agent.log_utils import log_section
from .output_schemas import validate_navigator_output

if TYPE_CHECKING:
    from ..agent.context import AgentContext
    from ..agent.messages.service import MessageManager

log = logging.getLogger(__name__)


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
        log.debug(
            "%sagent=%s model=%s prompt:\n%s",
            self._run_log_prefix(),
            self.id,
            self._llm.model_name or "?",
            json.dumps(chat_messages, ensure_ascii=False, indent=2),
        )
        if self._llm.supports_structured_output:
            return self._llm.chat_json(chat_messages, temperature=temperature)
        return self._llm.chat(chat_messages, temperature=temperature)

    def get_json_response(self, messages: list[dict] | None = None, temperature: float = 0.7) -> dict:
        parsed, _ = self.get_json_response_with_raw(messages, temperature)
        return parsed

    def _run_log_prefix(self) -> str:
        context = getattr(self, "_context", None)
        run_id = getattr(context, "run_id", "") if context else ""
        if run_id:
            return f"[run:{run_id[:8]}] "
        return ""

    def get_json_response_with_raw(
        self,
        messages: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> tuple[dict, str]:
        if self._message_manager:
            if self._llm.model_name:
                self._message_manager.settings.token_model = self._llm.model_name
            self._message_manager.cut_messages()
        msgs = messages if messages is not None else self._get_messages()
        chat_messages = convert_messages_for_chat(msgs)
        input_chars = len(json.dumps(chat_messages, ensure_ascii=False))
        try:
            input_tokens = sum(self._llm.count_message_tokens(m) for m in chat_messages)
        except Exception:
            input_tokens = 0

        prefix = self._run_log_prefix()
        model = self._llm.model_name or "?"
        branch = f"{prefix}│ "
        log.info(
            "%sagent=%s start model=%s input_chars=%d input_tokens=%d",
            branch,
            self.id,
            model,
            input_chars,
            input_tokens,
        )

        usage_before = self._llm.get_accumulated_usage()
        started = time.monotonic()
        try:
            response = self.invoke(messages, temperature)
        except HitlInterruptedError:
            raise
        except Exception as error:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            log.info(
                "%sagent=%s failed model=%s duration_ms=%d error=%s",
                branch,
                self.id,
                model,
                elapsed_ms,
                error,
            )
            raise classify_llm_error(error) from error

        elapsed_ms = int((time.monotonic() - started) * 1000)
        try:
            usage_after = self._llm.get_accumulated_usage()
            prompt_tokens = usage_after["prompt_tokens"] - usage_before["prompt_tokens"]
            completion_tokens = usage_after["completion_tokens"] - usage_before["completion_tokens"]
        except (AttributeError, TypeError, KeyError):
            prompt_tokens = 0
            completion_tokens = 0

        if not isinstance(response, str) or not response.strip():
            log.info(
                "%sagent=%s done model=%s duration_ms=%d output_chars=0",
                branch,
                self.id,
                model,
                elapsed_ms,
            )
            raise ResponseParseError("LLM returned empty content")

        log.debug(
            "%sagent=%s raw_output:\n%s",
            prefix,
            self.id,
            response,
        )
        generation_id = getattr(self._llm, "last_generation_id", None) or ""
        done_extra = f" generation_id={generation_id}" if generation_id else ""
        log.info(
            "%sagent=%s done model=%s duration_ms=%d output_chars=%d "
            "prompt_tokens=%d completion_tokens=%d output=%s%s",
            branch,
            self.id,
            model,
            elapsed_ms,
            len(response),
            prompt_tokens,
            completion_tokens,
            preview_text(response, 500),
            done_extra,
        )
        cleaned = remove_think_tags(response)
        try:
            parsed = extract_json_from_model_output(cleaned)
        except Exception as error:
            log.warning(
                "%sagent=%s JSON extract failed, using fallback parser: %s",
                prefix,
                self.id,
                error,
            )
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
            validated = validate_navigator_actions(fixed)
            if len(validated) < len(fixed):
                log.warning(
                    "%sagent=%s dropped %d invalid actions during validation (kept %d/%d)",
                    prefix,
                    self.id,
                    len(fixed) - len(validated),
                    len(validated),
                    len(fixed),
                )
            normalized["action"] = validated
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
