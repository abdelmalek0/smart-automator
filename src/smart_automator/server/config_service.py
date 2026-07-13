from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv, set_key

from ..config import Config, load_config
from ..server.paths import ENV_FILE, PRICING_FILE
from ..server.provider_utils import (
    UI_PROVIDERS,
    normalize_provider,
    provider_api_key_env_name,
    provider_api_key_is_set,
    runtime_provider,
)
from ..storage.llm_settings import LlmSettingsStore

log = logging.getLogger(__name__)

_DEFAULT_GROQ_PRICING = [
    {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "input": 0.59,
        "output": 0.79,
        "cache_read": 0.0,
    },
    {
        "provider": "groq",
        "model": "llama-3.1-8b-instant",
        "input": 0.05,
        "output": 0.08,
        "cache_read": 0.0,
    },
]


def reload_runtime_env() -> None:
    load_dotenv(ENV_FILE, override=True)


def build_config_response() -> dict:
    reload_runtime_env()
    config = load_config()
    settings = LlmSettingsStore().ensure_loaded()
    provider = normalize_provider(settings.provider or config.llm_provider)
    active = settings.get_provider(provider)
    runtime = runtime_provider(provider)
    model = active.model or (
        config.groq_model if runtime == "groq" else config.ollama_model
    )
    base_url = active.base_url or (
        "https://api.groq.com/openai/v1"
        if runtime == "groq"
        else config.ollama_base_url
    )
    provider_keys_set = {name: provider_api_key_is_set(name) for name in UI_PROVIDERS}
    provider_settings = {
        name: entry.to_dict() for name, entry in settings.providers.items()
    }
    fresh_profile = os.getenv("QA_FRESH_PROFILE", "false").lower() == "true"
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_set": provider_api_key_is_set(provider),
        "provider_keys_set": provider_keys_set,
        "provider_settings": provider_settings,
        "cdp_port": int(os.getenv("CDP_PORT", "9222")),
        "fresh_profile": fresh_profile,
        "chrome_user_data": os.getenv("CHROME_USER_DATA", ""),
    }


def apply_config_update(update) -> dict:
    reload_runtime_env()
    settings_store = LlmSettingsStore()
    settings = settings_store.ensure_loaded()
    provider = normalize_provider(update.provider or settings.provider)

    settings_store.update_active(
        provider=provider if update.provider is not None else None,
        base_url=update.base_url,
        model=update.model,
    )

    if not ENV_FILE.exists():
        ENV_FILE.write_text("")

    runtime = runtime_provider(provider)
    set_key(str(ENV_FILE), "LLM_PROVIDER", runtime)
    if update.model is not None:
        if runtime == "groq":
            set_key(str(ENV_FILE), "GROQ_MODEL", update.model)
        else:
            set_key(str(ENV_FILE), "OLLAMA_MODEL", update.model)
    if update.base_url is not None and runtime == "ollama":
        set_key(str(ENV_FILE), "OLLAMA_BASE_URL", update.base_url)
    if update.api_key is not None:
        ui_provider = (update.provider or settings.provider or provider).strip().lower()
        key_env = provider_api_key_env_name(ui_provider)
        if key_env:
            set_key(str(ENV_FILE), key_env, update.api_key)
    if update.fresh_profile is not None:
        set_key(str(ENV_FILE), "QA_FRESH_PROFILE", "true" if update.fresh_profile else "false")

    reload_runtime_env()
    return build_config_response()


def check_llm_connection() -> None:
    reload_runtime_env()
    config = load_config()
    settings = LlmSettingsStore().ensure_loaded()
    provider = runtime_provider(settings.provider or config.llm_provider)
    if provider == "ollama":
        from ..llm.ollama import OllamaLLM

        llm = OllamaLLM(config)
    else:
        from ..llm.groq import GroqLLM

        llm = GroqLLM(config)
    llm.chat([{"role": "user", "content": "Reply with OK only."}], temperature=0)


def load_pricing() -> list[dict]:
    if PRICING_FILE.exists():
        try:
            with open(PRICING_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to read pricing file %s", PRICING_FILE)
    return list(_DEFAULT_GROQ_PRICING)


def save_pricing(entries: list[dict]) -> int:
    PRICING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PRICING_FILE, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")
    return len(entries)


def config_for_run() -> Config:
    reload_runtime_env()
    config = load_config()
    settings = LlmSettingsStore().ensure_loaded()
    runtime = runtime_provider(settings.provider or config.llm_provider)
    active = settings.get_provider(settings.provider)
    config.llm_provider = runtime
    if runtime == "groq":
        if active.model:
            config.groq_model = active.model
    else:
        if active.model:
            config.ollama_model = active.model
        if active.base_url:
            config.ollama_base_url = active.base_url
    return config
