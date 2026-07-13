from __future__ import annotations

import os

SUPPORTED_PROVIDERS = ("groq", "ollama")
UI_PROVIDERS = ("groq", "ollama-cloud", "ollama", "google")

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
    "ollama-cloud": "OLLAMA_API_KEY",
}


def normalize_provider(provider: str) -> str:
    key = (provider or "groq").strip().lower()
    if key in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[key]
    if key in SUPPORTED_PROVIDERS:
        return key
    if key in ("ollama-cloud", "google"):
        return key
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
    if canonical == "ollama":
        return "http://localhost:11434"
    return "https://ollama.com"


def default_model_for_provider(provider: str) -> str:
    canonical = normalize_provider(provider)
    if canonical == "groq":
        return "llama-3.3-70b-versatile"
    if canonical == "google":
        return "gemini-2.5-flash"
    if canonical == "ollama":
        return "llama3.2"
    return "gemma4:31b-cloud"


def provider_api_key_env_name(provider: str) -> str | None:
    key = (provider or "groq").strip().lower()
    if key in _PROVIDER_KEY_ENV:
        return _PROVIDER_KEY_ENV[key]
    return _PROVIDER_KEY_ENV.get(normalize_provider(provider))


def provider_api_key_is_set(provider: str) -> bool:
    env_name = provider_api_key_env_name(provider)
    if not env_name:
        return False
    return bool(os.getenv(env_name, "").strip())
