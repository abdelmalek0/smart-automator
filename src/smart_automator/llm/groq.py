import json

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


def _body_preview(body: dict, *, limit: int = 500) -> str:
    try:
        text = json.dumps(body, ensure_ascii=False)
    except TypeError:
        text = repr(body)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _extract_chat_completion_content(body: dict) -> str:
    error = body.get("error")
    if error:
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or json.dumps(error)
        else:
            message = str(error)
        raise ValueError(f"LLM API returned error payload: {message}")

    choices = body.get("choices")
    if not choices:
        keys = ", ".join(sorted(body.keys())) or "(empty)"
        raise ValueError(
            f"LLM API response missing choices (keys: {keys}): {_body_preview(body)}"
        )

    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError(
            f"LLM API response has invalid choices[0]: {_body_preview(body)}"
        )

    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError(
            f"LLM API response missing message in choices[0]: {_body_preview(body)}"
        )

    content = message.get("content")
    if content is None:
        raise ValueError(
            f"LLM API response missing message content: {_body_preview(body)}"
        )

    return content


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
        self._timeout = 60.0
        self._client = httpx.Client(timeout=self._timeout)

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

    async def achat(self, messages: list[dict], temperature: float = 0.7) -> str:
        url, headers, payload = self._chat_request(
            messages, temperature=temperature, json_mode=False
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
        return self._handle_chat_response(response)

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

    def _chat_request(
        self, messages: list[dict], *, temperature: float, json_mode: bool
    ) -> tuple[str, dict[str, str], dict]:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self._provider == "openrouter":
            # Temporary cap while OpenRouter routing/models are being tuned.
            payload["max_tokens"] = 20000
            if self._openrouter_provider:
                payload["provider"] = {
                    "only": [self._openrouter_provider],
                    "allow_fallbacks": False,
                }
        return self._base_url, self._headers(), payload

    def _handle_chat_response(self, response: httpx.Response) -> str:
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
        return _extract_chat_completion_content(body)

    def _post(self, messages: list[dict], *, temperature: float, json_mode: bool) -> str:
        self._check_abort()
        url, headers, payload = self._chat_request(
            messages, temperature=temperature, json_mode=json_mode
        )
        response = self._client.post(url, headers=headers, json=payload)
        return self._handle_chat_response(response)

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass


# Backward-compatible alias
GroqLLM = OpenAICompatLLM
