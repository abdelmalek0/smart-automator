from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
import threading

from .tokens import count_message_tokens, count_text_tokens


class BaseLLM(ABC):
    def __init__(self):
        self._cancel_event: threading.Event | None = None
        self._interrupt_check: Callable[[], bool] | None = None
        self._usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_tokens": 0,
        }
        self._billing_provider: str = ""

    @property
    def billing_provider(self) -> str:
        """UI provider id used for pricing lookup (e.g. groq, ollama-cloud)."""
        return self._billing_provider

    def set_billing_provider(self, provider: str) -> None:
        self._billing_provider = (provider or "").strip()

    @property
    def model_name(self) -> str | None:
        return None

    @property
    def supports_structured_output(self) -> bool:
        return False

    def set_cancel_event(self, cancel_event: threading.Event | None) -> None:
        self._cancel_event = cancel_event

    def set_interrupt_check(self, interrupt_check: Callable[[], bool] | None) -> None:
        self._interrupt_check = interrupt_check

    def _check_cancelled(self) -> None:
        if self._cancel_event and self._cancel_event.is_set():
            from ..agents.errors import RequestCancelledError

            raise RequestCancelledError("LLM request cancelled")

    def _check_hitl_interrupt(self) -> None:
        if self._interrupt_check and self._interrupt_check():
            from ..agents.errors import HitlInterruptedError

            raise HitlInterruptedError("HITL interrupt")

    def _check_abort(self) -> None:
        self._check_cancelled()
        self._check_hitl_interrupt()

    def _call_with_retry(self, operation, **kwargs):
        from .retry import call_with_retry

        return call_with_retry(
            operation,
            cancel_check=self._check_abort,
            wake=self._cancel_event,
            **kwargs,
        )

    def _record_usage(self, usage: dict) -> None:
        self._usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        self._usage["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        self._usage["cache_tokens"] += int(usage.get("cache_tokens", 0) or 0)

    def get_accumulated_usage(self) -> dict[str, int]:
        return dict(self._usage)

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        pass

    async def achat(self, messages: list[dict], temperature: float = 0.7) -> str:
        """Non-blocking chat for FastAPI (connection check). Agent still uses chat()."""
        raise NotImplementedError(f"{type(self).__name__} does not implement achat")

    def chat_json(self, messages: list[dict], temperature: float = 0.7) -> str:
        return self.chat(messages, temperature=temperature)

    def count_tokens(self, text: str) -> int:
        return count_text_tokens(text, model=self.model_name)

    def count_message_tokens(self, message: dict) -> int:
        return count_message_tokens(message, model=self.model_name)
