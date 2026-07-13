from __future__ import annotations

from abc import ABC, abstractmethod
import threading

from .tokens import count_message_tokens, count_text_tokens


class BaseLLM(ABC):
    def __init__(self):
        self._cancel_event: threading.Event | None = None

    @property
    def model_name(self) -> str | None:
        return None

    @property
    def supports_structured_output(self) -> bool:
        return False

    def set_cancel_event(self, cancel_event: threading.Event | None) -> None:
        self._cancel_event = cancel_event

    def _check_cancelled(self) -> None:
        if self._cancel_event and self._cancel_event.is_set():
            from ..agents.errors import RequestCancelledError

            raise RequestCancelledError("LLM request cancelled")

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        pass

    def chat_json(self, messages: list[dict], temperature: float = 0.7) -> str:
        return self.chat(messages, temperature=temperature)

    def count_tokens(self, text: str) -> int:
        return count_text_tokens(text, model=self.model_name)

    def count_message_tokens(self, message: dict) -> int:
        return count_message_tokens(message, model=self.model_name)
