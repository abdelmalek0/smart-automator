import httpx

from .base import BaseLLM
from .retry import call_with_retry
from .structured_output import ensure_json_keyword_in_messages
from ..config import Config


class GroqLLM(BaseLLM):
    def __init__(self, config: Config):
        super().__init__()
        self._api_key = config.groq_api_key
        self._model = config.groq_model
        self._base_url = "https://api.groq.com/openai/v1/chat/completions"
        self._client = httpx.Client(timeout=60.0)

    @property
    def model_name(self) -> str | None:
        return self._model

    @property
    def supports_structured_output(self) -> bool:
        return True

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        return call_with_retry(
            lambda: self._post(messages, temperature=temperature, json_mode=False),
            cancel_check=self._check_cancelled,
        )

    def chat_json(self, messages: list[dict], temperature: float = 0.7) -> str:
        prepared = ensure_json_keyword_in_messages(messages)
        try:
            return call_with_retry(
                lambda: self._post(prepared, temperature=temperature, json_mode=True),
                cancel_check=self._check_cancelled,
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 400:
                raise
            return call_with_retry(
                lambda: self._post(messages, temperature=temperature, json_mode=False),
                cancel_check=self._check_cancelled,
            )

    def _post(self, messages: list[dict], *, temperature: float, json_mode: bool) -> str:
        self._check_cancelled()
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = self._client.post(
            self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            detail = response.text.strip()
            if detail:
                raise httpx.HTTPStatusError(
                    f"Groq API error {response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass
