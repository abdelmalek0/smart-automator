import httpx

from .base import BaseLLM
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
        self._timeout = 120.0
        self._client = httpx.Client(timeout=self._timeout)

    @property
    def model_name(self) -> str | None:
        return self._model

    @property
    def supports_structured_output(self) -> bool:
        return True

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        return self._call_with_retry(
            lambda: self._post(messages, temperature=temperature, json_mode=False),
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
            return self._call_with_retry(
                lambda: self._post(prepared, temperature=temperature, json_mode=True),
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 400:
                raise
            return self._call_with_retry(
                lambda: self._post(messages, temperature=temperature, json_mode=False),
            )

    def _chat_request(
        self, messages: list[dict], *, temperature: float, json_mode: bool
    ) -> tuple[str, dict[str, str], dict]:
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
        return f"{self._base_url}/api/chat", headers, payload

    def _handle_chat_response(self, response: httpx.Response) -> str:
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
