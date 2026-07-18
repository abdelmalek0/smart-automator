from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv, set_key

from ..config import (
    Config,
    browser_session_mode,
    default_chrome_user_data,
    load_config,
    resolve_chrome_user_data,
)
from ..server.paths import ENV_FILE, PRICING_FILE
from ..server.provider_utils import (
    UI_PROVIDERS,
    coerce_provider_base_url,
    coerce_provider_model,
    default_base_url,
    default_model_for_provider,
    format_llm_connection_error,
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
    if runtime == "groq":
        model = active.model or config.groq_model
    elif runtime == "google":
        model = active.model or config.google_model
    else:
        model = active.model or config.ollama_model
    base_url = active.base_url or default_base_url(provider)
    provider_keys_set = {name: provider_api_key_is_set(name) for name in UI_PROVIDERS}
    provider_settings = {
        name: entry.to_dict() for name, entry in settings.providers.items()
    }
    fresh_profile = os.getenv("QA_FRESH_PROFILE", "false").lower() == "true"
    cdp_url = os.getenv("CDP_URL", "")
    chrome_user_data = os.getenv("CHROME_USER_DATA", "")
    session_mode = browser_session_mode(cdp_url=cdp_url, fresh_profile=fresh_profile)
    effective_chrome_user_data = resolve_chrome_user_data(
        chrome_user_data,
        fresh_profile=fresh_profile,
    )
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_set": provider_api_key_is_set(provider),
        "provider_keys_set": provider_keys_set,
        "provider_settings": provider_settings,
        "cdp_port": int(os.getenv("CDP_PORT", "9222")),
        "cdp_url": cdp_url,
        "fresh_profile": fresh_profile,
        "chrome_user_data": chrome_user_data,
        "effective_chrome_user_data": effective_chrome_user_data,
        "default_chrome_user_data": default_chrome_user_data(),
        "browser_session_mode": session_mode,
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
    settings = settings_store.ensure_loaded()
    active = settings.get_provider(provider)

    if not ENV_FILE.exists():
        ENV_FILE.write_text("")

    runtime = runtime_provider(provider)
    set_key(str(ENV_FILE), "LLM_PROVIDER", runtime)
    if update.model is not None:
        if runtime == "groq":
            set_key(str(ENV_FILE), "GROQ_MODEL", active.model)
        elif runtime == "google":
            set_key(str(ENV_FILE), "GOOGLE_MODEL", active.model)
        else:
            set_key(str(ENV_FILE), "OLLAMA_MODEL", active.model)
    if update.base_url is not None:
        if runtime == "ollama":
            set_key(str(ENV_FILE), "OLLAMA_BASE_URL", active.base_url)
    if update.api_key is not None:
        ui_provider = (update.provider or settings.provider or provider).strip().lower()
        key_env = provider_api_key_env_name(ui_provider)
        if key_env:
            set_key(str(ENV_FILE), key_env, update.api_key)
    if update.fresh_profile is not None:
        set_key(str(ENV_FILE), "QA_FRESH_PROFILE", "true" if update.fresh_profile else "false")
    if update.chrome_user_data is not None:
        set_key(str(ENV_FILE), "CHROME_USER_DATA", update.chrome_user_data.strip())
    if update.cdp_url is not None:
        set_key(str(ENV_FILE), "CDP_URL", update.cdp_url.strip())

    reload_runtime_env()
    return build_config_response()


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


def _pricing_lookup(provider: str, model: str) -> dict | None:
    canonical = normalize_provider(provider)
    runtime = runtime_provider(canonical)
    for entry in load_pricing():
        entry_provider = normalize_provider(str(entry.get("provider", "")))
        entry_runtime = runtime_provider(entry_provider)
        if entry_runtime == runtime and str(entry.get("model", "")) == model:
            return entry
    return None


def compute_cost_usd(
    provider: str,
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_tokens: int,
) -> float | None:
    canonical = normalize_provider(provider)
    runtime = runtime_provider(canonical)
    row = _pricing_lookup(canonical, model)
    if row is None:
        if runtime == "ollama":
            return 0.0
        return None
    input_rate = float(row.get("input", 0) or 0)
    output_rate = float(row.get("output", 0) or 0)
    cache_rate = float(row.get("cache_read", 0) or 0)
    return (
        prompt_tokens * input_rate
        + completion_tokens * output_rate
        + cache_tokens * cache_rate
    ) / 1_000_000


def config_for_run() -> Config:
    reload_runtime_env()
    config = load_config()
    settings = LlmSettingsStore().ensure_loaded()
    ui_provider = normalize_provider(settings.provider or config.llm_provider)
    runtime = runtime_provider(ui_provider)
    active = settings.get_provider(ui_provider)
    config.llm_provider = runtime
    config.active_provider = ui_provider
    config.active_model = active.model or default_model_for_provider(ui_provider)
    if runtime == "groq":
        config.groq_model = config.active_model
        config.openai_base_url = active.base_url or default_base_url("groq")
    elif runtime == "google":
        config.google_model = config.active_model
        config.openai_base_url = active.base_url or default_base_url("google")
    else:
        config.ollama_model = config.active_model
        if active.base_url:
            config.ollama_base_url = active.base_url
    return config


def _update_has_llm_fields(update) -> bool:
    if update is None:
        return False
    return any(
        getattr(update, field) is not None
        for field in ("provider", "base_url", "model", "api_key")
    )


def config_for_check(update=None) -> Config:
    """Build a Config for connection testing from saved settings or an optional form payload."""
    reload_runtime_env()
    config = load_config()
    settings = LlmSettingsStore().ensure_loaded()

    if not _update_has_llm_fields(update):
        return config_for_run()

    ui_provider = normalize_provider(
        update.provider if update.provider is not None else settings.provider or config.llm_provider
    )
    active = settings.get_provider(ui_provider)
    base_url = (
        coerce_provider_base_url(ui_provider, update.base_url)
        if update.base_url is not None
        else coerce_provider_base_url(ui_provider, active.base_url)
    )
    model = (
        coerce_provider_model(ui_provider, update.model, base_url=base_url)
        if update.model is not None
        else coerce_provider_model(ui_provider, active.model, base_url=base_url)
    )

    runtime = runtime_provider(ui_provider)
    config.llm_provider = runtime
    config.active_provider = ui_provider
    config.active_model = model

    if update.api_key is not None:
        key_env = provider_api_key_env_name(ui_provider)
        if key_env == "GROQ_API_KEY":
            config.groq_api_key = update.api_key
        elif key_env == "GOOGLE_API_KEY":
            config.google_api_key = update.api_key
        elif key_env == "OLLAMA_API_KEY":
            config.ollama_api_key = update.api_key

    if runtime == "groq":
        config.groq_model = model
        config.openai_base_url = base_url or default_base_url("groq")
    elif runtime == "google":
        config.google_model = model
        config.openai_base_url = base_url or default_base_url("google")
    else:
        config.ollama_model = model
        config.ollama_base_url = base_url or default_base_url(ui_provider)
    return config


def check_llm_connection(update=None) -> None:
    config = config_for_check(update)
    from ..main import create_llm

    try:
        llm = create_llm(config)
        llm.chat([{"role": "user", "content": "Reply with OK only."}], temperature=0)
    except BaseException as exc:
        raise RuntimeError(format_llm_connection_error(exc)) from exc
