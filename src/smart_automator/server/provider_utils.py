from __future__ import annotations

import os

import httpx

SUPPORTED_PROVIDERS = ("groq", "ollama", "google", "openrouter")
UI_PROVIDERS = ("groq", "ollama-cloud", "google", "openrouter")

_PROVIDER_ALIASES = {
    "ollama-local": "ollama",
    "ollama_local": "ollama",
    "local": "ollama",
    "gemini": "google",
    "google-gemini": "google",
    "google_gemini": "google",
}

_PROVIDER_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama-cloud": "OLLAMA_CLOUD_API_KEY",
}

_PROVIDER_MODEL_ENV = {
    "groq": "GROQ_MODEL",
    "google": "GOOGLE_MODEL",
    "openrouter": "OPENROUTER_MODEL",
    "ollama": "OLLAMA_MODEL",
    "ollama-cloud": "OLLAMA_CLOUD_MODEL",
}

_PROVIDER_BASE_URL_ENV = {
    "ollama": "OLLAMA_BASE_URL",
    "ollama-cloud": "OLLAMA_CLOUD_BASE_URL",
}

_LOCAL_OLLAMA_DEFAULT_URL = "http://localhost:11434"
_CLOUD_OLLAMA_DEFAULT_URL = "https://ollama.com"


def is_ollama_cloud_url(base_url: str) -> bool:
    return "ollama.com" in (base_url or "").rstrip("/").lower()


def is_ollama_local_url(base_url: str) -> bool:
    url = (base_url or "").rstrip("/").lower()
    if not url:
        return False
    return not is_ollama_cloud_url(url)


def is_cloud_ollama_model(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    if name.endswith(":cloud"):
        return True
    return name in {"gemma4:31b-cloud", "qwen3.5:cloud"}


def coerce_provider_base_url(provider: str, base_url: str) -> str:
    """Return a base URL appropriate for the UI provider id."""
    canonical = normalize_provider(provider)
    url = (base_url or "").strip()
    if canonical == "ollama":
        if not url or is_ollama_cloud_url(url):
            return _LOCAL_OLLAMA_DEFAULT_URL
        return url.rstrip("/")
    if canonical == "ollama-cloud":
        if not url or is_ollama_local_url(url):
            return _CLOUD_OLLAMA_DEFAULT_URL
        return url.rstrip("/")
    if url:
        return url.rstrip("/")
    return default_base_url(canonical)


def coerce_provider_model(provider: str, model: str, *, base_url: str) -> str:
    """Return a model name appropriate for the UI provider id and base URL."""
    canonical = normalize_provider(provider)
    name = (model or "").strip()
    if canonical == "ollama":
        if is_ollama_cloud_url(base_url) or is_cloud_ollama_model(name):
            return default_model_for_provider("ollama")
        if name:
            return name
        return default_model_for_provider("ollama")
    if canonical == "ollama-cloud":
        if name:
            return name
        return default_model_for_provider("ollama-cloud")
    if name:
        return name
    return default_model_for_provider(canonical)


def normalize_provider(provider: str) -> str:
    key = (provider or "groq").strip().lower()
    if key in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[key]
    if key in SUPPORTED_PROVIDERS:
        return key
    if key == "ollama-cloud":
        return key
    return "groq"


def coerce_ui_provider(provider: str) -> str:
    """Map a provider id to one that appears in Settings (UI_PROVIDERS)."""
    canonical = normalize_provider(provider)
    if canonical in UI_PROVIDERS:
        return canonical
    return "groq"


def runtime_provider(provider: str) -> str:
    """Map UI provider id to a provider smart-automator can run."""
    canonical = normalize_provider(provider)
    if canonical == "ollama-cloud":
        return "ollama"
    if canonical in SUPPORTED_PROVIDERS:
        return canonical
    return "groq"


def default_base_url(provider: str) -> str:
    canonical = normalize_provider(provider)
    if canonical == "groq":
        return "https://api.groq.com/openai/v1"
    if canonical == "google":
        return "https://generativelanguage.googleapis.com/v1beta/openai"
    if canonical == "openrouter":
        return "https://openrouter.ai/api/v1"
    if canonical == "ollama":
        return _LOCAL_OLLAMA_DEFAULT_URL
    return _CLOUD_OLLAMA_DEFAULT_URL


def default_model_for_provider(provider: str) -> str:
    canonical = normalize_provider(provider)
    if canonical == "groq":
        return "llama-3.3-70b-versatile"
    if canonical == "google":
        return "gemini-2.5-flash"
    if canonical == "openrouter":
        return "deepseek/deepseek-v4-flash-0731"
    if canonical == "ollama":
        return "llama3.2"
    return "gemma4:31b-cloud"


def provider_api_key_env_name(provider: str) -> str | None:
    key = (provider or "groq").strip().lower()
    if key in _PROVIDER_KEY_ENV:
        return _PROVIDER_KEY_ENV[key]
    return _PROVIDER_KEY_ENV.get(normalize_provider(provider))


def provider_model_env_name(provider: str) -> str:
    canonical = normalize_provider(provider)
    return _PROVIDER_MODEL_ENV.get(canonical, "GROQ_MODEL")


def provider_base_url_env_name(provider: str) -> str | None:
    canonical = normalize_provider(provider)
    return _PROVIDER_BASE_URL_ENV.get(canonical)


def provider_api_key_is_set(provider: str) -> bool:
    env_name = provider_api_key_env_name(provider)
    if not env_name:
        return False
    return bool(os.getenv(env_name, "").strip())


def format_llm_connection_error(error: BaseException) -> str:
    """Return a user-facing message for LLM connection failures."""
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        request_url = str(error.request.url) if error.request is not None else ""
        if status == 403 and "ollama.com" in request_url.lower():
            return (
                "Ollama Cloud returned 403 Forbidden. Check that OLLAMA_CLOUD_API_KEY is valid "
                "(https://ollama.com/settings/keys) and that your account can use the "
                "selected model."
            )
        if status == 401 and "ollama.com" in request_url.lower():
            return (
                "Ollama Cloud rejected the API key (401). Set a valid OLLAMA_CLOUD_API_KEY in "
                "Settings or .env."
            )
    message = str(error)
    lowered = message.lower()
    if "403" in message and "forbidden" in lowered and "ollama.com" in lowered:
        return (
            "Ollama Cloud returned 403 Forbidden. Check that OLLAMA_CLOUD_API_KEY is valid "
            "(https://ollama.com/settings/keys) and that your account can use the "
            "selected model."
        )
    if "401" in message and "ollama.com" in lowered:
        return (
            "Ollama Cloud rejected the API key (401). Set a valid OLLAMA_CLOUD_API_KEY in "
            "Settings or .env."
        )
    return message
