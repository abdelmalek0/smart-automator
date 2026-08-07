import httpx

from .base import BaseLLM
from .retry import call_with_retry
from .structured_output import ensure_json_keyword_in_messages
from ..config import Config
from ..server.provider_utils import default_base_url


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


class OpenAICompatLLM(BaseLLM):
    """OpenAI-compatible chat client for Groq, Google Gemini, OpenRouter, and similar APIs."""

    def __init__(self, config: Config, *, provider: str | None = None):
        super().__init__()
        selected = (provider or config.llm_provider or "groq").strip().lower()
        self._provider = selected
        self._openrouter_provider = ""
        self._last_generation_id = ""
        if selected == "google":
            self._api_key = config.google_api_key
            self._model = config.active_model or config.google_model
            base = config.openai_base_url or default_base_url("google")
        elif selected == "openrouter":
            self._api_key = config.openrouter_api_key
            self._model = config.active_model or config.openrouter_model
            base = config.openai_base_url or default_base_url("openrouter")
            self._openrouter_provider = (config.openrouter_provider or "").strip()
        else:
            self._api_key = config.groq_api_key
            self._model = config.active_model or config.groq_model
            base = config.openai_base_url or default_base_url("groq")
        self._base_url = _chat_completions_url(base)
        self._client = httpx.Client(timeout=60.0)

    @property
    def model_name(self) -> str | None:
        return self._model

    @property
    def last_generation_id(self) -> str:
        return self._last_generation_id

    @property
    def supports_structured_output(self) -> bool:
        return True

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        return call_with_retry(
            lambda: self._post(messages, temperature=temperature, json_mode=False),
            cancel_check=self._check_abort,
        )

    def chat_json(self, messages: list[dict], temperature: float = 0.7) -> str:
        prepared = ensure_json_keyword_in_messages(messages)
        try:
            return call_with_retry(
                lambda: self._post(prepared, temperature=temperature, json_mode=True),
                cancel_check=self._check_abort,
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 400:
                raise
            return call_with_retry(
                lambda: self._post(messages, temperature=temperature, json_mode=False),
                cancel_check=self._check_abort,
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/smart-automator"
            headers["X-Title"] = "smart-automator"
        return headers

    def _post(self, messages: list[dict], *, temperature: float, json_mode: bool) -> str:
        self._check_abort()
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self._provider == "openrouter" and self._openrouter_provider:
            payload["provider"] = {
                "only": [self._openrouter_provider],
                "allow_fallbacks": False,
            }
        response = self._client.post(
            self._base_url,
            headers=self._headers(),
            json=payload,
        )
        if response.status_code >= 400:
            detail = response.text.strip()
            if detail:
                raise httpx.HTTPStatusError(
                    f"LLM API error {response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
        response.raise_for_status()
        body = response.json()
        self._last_generation_id = str(body.get("id") or "").strip()
        usage = body.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        self._record_usage(
            {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "cache_tokens": int(details.get("cached_tokens", 0) or 0),
            }
        )
        return body["choices"][0]["message"]["content"]

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass


# Backward-compatible alias
GroqLLM = OpenAICompatLLM
