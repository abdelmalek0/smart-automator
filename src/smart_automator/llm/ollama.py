import httpx

from .base import BaseLLM
from .retry import call_with_retry
from .structured_output import ensure_json_keyword_in_messages
from ..config import Config

from ..server.provider_utils import is_ollama_cloud_url


class OllamaLLM(BaseLLM):
    def __init__(self, config: Config):
        super().__init__()
        self._base_url = config.ollama_base_url.rstrip("/")
        self._model = config.ollama_model
        self._api_key = config.ollama_api_key.strip()
        if is_ollama_cloud_url(self._base_url) and not self._api_key:
            raise ValueError(
                "OLLAMA_CLOUD_API_KEY is required for Ollama Cloud (https://ollama.com). "
                "Create a key at https://ollama.com/settings/keys and set OLLAMA_CLOUD_API_KEY in .env."
            )
        self._client = httpx.Client(timeout=120.0)

    @property
    def model_name(self) -> str | None:
        return self._model

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

    def _post(self, messages: list[dict], *, temperature: float, json_mode: bool) -> str:
        self._check_abort()
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = self._client.post(
            f"{self._base_url}/api/chat",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        self._record_usage(
            {
                "prompt_tokens": int(body.get("prompt_eval_count", 0) or 0),
                "completion_tokens": int(body.get("eval_count", 0) or 0),
                "cache_tokens": 0,
            }
        )
        return body["message"]["content"]

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass
