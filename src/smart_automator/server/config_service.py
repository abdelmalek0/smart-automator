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
from ..browser.chrome_profiles import (
    discover_chrome_profiles,
    format_effective_chrome_profile,
)
from ..browser.chrome_profile_mirror import (
    chrome_profile_mirror_path,
    format_mirrored_chrome_profile,
)
from ..server.paths import ENV_FILE, PRICING_FILE
from ..server.provider_utils import (
    UI_PROVIDERS,
    coerce_provider_base_url,
    coerce_provider_model,
    coerce_ui_provider,
    default_base_url,
    default_model_for_provider,
    format_llm_connection_error,
    is_cloud_ollama_model,
    is_ollama_cloud_url,
    normalize_provider,
    provider_api_key_env_name,
    provider_api_key_is_set,
    provider_base_url_env_name,
    provider_model_env_name,
    runtime_provider,
)
from ..storage.llm_settings import LlmSettingsStore
from ..storage.user_llm import UserLlmPrefs, UserLlmStore

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
    migrate_legacy_ollama_env()


def migrate_legacy_ollama_env() -> None:
    """Migrate shared OLLAMA_* vars to split local/cloud vars."""
    provider = normalize_provider(os.environ.get("LLM_PROVIDER", "groq"))
    legacy_base = os.environ.get("OLLAMA_BASE_URL", "").strip()
    legacy_model = os.environ.get("OLLAMA_MODEL", "").strip()
    legacy_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    cloud_model = os.environ.get("OLLAMA_CLOUD_MODEL", "").strip()
    cloud_base = os.environ.get("OLLAMA_CLOUD_BASE_URL", "").strip()
    cloud_key = os.environ.get("OLLAMA_CLOUD_API_KEY", "").strip()
    looks_cloud = provider == "ollama-cloud" or is_ollama_cloud_url(legacy_base)
    needs_cloud_migration = looks_cloud and (
        (legacy_model and not cloud_model)
        or (legacy_base and not cloud_base)
        or (legacy_key and not cloud_key)
    )
    if not needs_cloud_migration and not (
        provider == "ollama" and looks_cloud and (legacy_base or is_cloud_ollama_model(legacy_model))
    ):
        return
    if not ENV_FILE.exists():
        ENV_FILE.write_text("")
    env_path = str(ENV_FILE)
    if needs_cloud_migration:
        if legacy_model and not cloud_model:
            set_key(env_path, "OLLAMA_CLOUD_MODEL", legacy_model)
            os.environ["OLLAMA_CLOUD_MODEL"] = legacy_model
        if legacy_base and not cloud_base:
            set_key(env_path, "OLLAMA_CLOUD_BASE_URL", legacy_base)
            os.environ["OLLAMA_CLOUD_BASE_URL"] = legacy_base
        if legacy_key and not cloud_key:
            set_key(env_path, "OLLAMA_CLOUD_API_KEY", legacy_key)
            os.environ["OLLAMA_CLOUD_API_KEY"] = legacy_key
    if provider == "ollama" and looks_cloud:
        local_base = default_base_url("ollama")
        local_model = default_model_for_provider("ollama")
        if legacy_base != local_base:
            set_key(env_path, "OLLAMA_BASE_URL", local_base)
            os.environ["OLLAMA_BASE_URL"] = local_base
        if is_cloud_ollama_model(legacy_model) or legacy_model != local_model:
            set_key(env_path, "OLLAMA_MODEL", local_model)
            os.environ["OLLAMA_MODEL"] = local_model


def _chrome_profile_display_name(user_data_dir: str, profile_directory: str) -> str:
    if not profile_directory:
        return ""
    target_id = f"{user_data_dir}|{profile_directory}"
    for profile in discover_chrome_profiles():
        if profile.id == target_id:
            return profile.name
    return profile_directory


def _active_model(config: Config, ui_provider: str) -> str:
    canonical = normalize_provider(ui_provider)
    if canonical == "groq":
        return config.groq_model
    if canonical == "google":
        return config.google_model
    if canonical == "openrouter":
        return config.openrouter_model
    if canonical == "ollama-cloud":
        return config.ollama_cloud_model
    return config.ollama_model


def _active_base_url(config: Config, ui_provider: str, *, catalog_base_url: str) -> str:
    canonical = normalize_provider(ui_provider)
    if canonical == "ollama":
        return config.ollama_base_url or default_base_url("ollama")
    if canonical == "ollama-cloud":
        return config.ollama_cloud_base_url or default_base_url("ollama-cloud")
    if catalog_base_url:
        return catalog_base_url
    return default_base_url(canonical)


def _clear_provider_api_keys(config: Config) -> None:
    config.groq_api_key = ""
    config.google_api_key = ""
    config.openrouter_api_key = ""
    config.ollama_cloud_api_key = ""
    config.ollama_api_key = ""


def _apply_api_key_to_config(config: Config, ui_provider: str, api_key: str) -> None:
    token = (api_key or "").strip()
    if not token:
        return
    key_env = provider_api_key_env_name(ui_provider)
    if key_env == "GROQ_API_KEY":
        config.groq_api_key = token
    elif key_env == "GOOGLE_API_KEY":
        config.google_api_key = token
    elif key_env == "OPENROUTER_API_KEY":
        config.openrouter_api_key = token
    elif key_env == "OLLAMA_CLOUD_API_KEY":
        config.ollama_cloud_api_key = token
        config.ollama_api_key = token


def _apply_user_llm_to_config(config: Config, prefs: UserLlmPrefs) -> Config:
    """Overlay per-user provider/model/keys onto a Config built from env/catalog."""
    settings = LlmSettingsStore().ensure_loaded()
    ui_provider = coerce_ui_provider(prefs.provider)
    catalog = settings.get_provider(ui_provider)
    model = prefs.selected_model(ui_provider)
    model = coerce_provider_model(ui_provider, model, base_url=catalog.base_url)
    runtime = runtime_provider(ui_provider)

    config.llm_provider = runtime
    config.active_provider = ui_provider
    config.active_model = model

    # Per-user mode must not inherit shared .env API keys.
    _clear_provider_api_keys(config)
    for name in UI_PROVIDERS:
        key = prefs.api_key_for(name)
        if key:
            _apply_api_key_to_config(config, name, key)

    if runtime == "groq":
        config.groq_model = model
        config.openai_base_url = catalog.base_url or default_base_url("groq")
    elif runtime == "google":
        config.google_model = model
        config.openai_base_url = catalog.base_url or default_base_url("google")
    elif runtime == "openrouter":
        config.openrouter_model = model
        config.openai_base_url = catalog.base_url or default_base_url("openrouter")
    else:
        config.ollama_model = model
        if ui_provider == "ollama-cloud":
            config.ollama_base_url = catalog.base_url or default_base_url("ollama-cloud")
            config.ollama_cloud_base_url = config.ollama_base_url
            if prefs.api_key_for("ollama-cloud"):
                config.ollama_api_key = prefs.api_key_for("ollama-cloud")
                config.ollama_cloud_api_key = config.ollama_api_key
        else:
            if not config.ollama_base_url:
                config.ollama_base_url = catalog.base_url or default_base_url("ollama")
            config.ollama_api_key = ""
    return config


def build_config_response(user_id: str | None = None) -> dict:
    reload_runtime_env()
    config = load_config()
    settings = LlmSettingsStore().ensure_loaded()

    prefs: UserLlmPrefs | None = None
    if user_id:
        prefs = UserLlmStore(user_id).load()
        provider = coerce_ui_provider(prefs.provider)
        model = prefs.selected_model(provider)
        provider_keys_set = {name: prefs.api_key_is_set(name) for name in UI_PROVIDERS}
        api_key_set = prefs.api_key_is_set(provider)
        selected_models = {
            name: prefs.models.get(name) or default_model_for_provider(name)
            for name in UI_PROVIDERS
        }
        for name, value in prefs.models.items():
            if value:
                selected_models[name] = value
    else:
        provider = coerce_ui_provider(config.llm_provider)
        model = _active_model(config, provider) or default_model_for_provider(provider)
        provider_keys_set = {name: provider_api_key_is_set(name) for name in UI_PROVIDERS}
        api_key_set = provider_api_key_is_set(provider)
        selected_models = {
            name: _active_model(config, name) or default_model_for_provider(name)
            for name in UI_PROVIDERS
        }

    catalog = settings.get_provider(provider)
    model = coerce_provider_model(provider, model, base_url=catalog.base_url)
    base_url = _active_base_url(config, provider, catalog_base_url=catalog.base_url)
    if prefs is not None:
        # Catalog owns shared base URLs for all users.
        base_url = catalog.base_url or default_base_url(provider)

    provider_settings = {
        name: settings.get_provider(name).to_dict() for name in UI_PROVIDERS
    }

    fresh_profile = os.getenv("QA_FRESH_PROFILE", "true").lower() == "true"
    cdp_url = os.getenv("CDP_URL", "")
    chrome_user_data = os.getenv("CHROME_USER_DATA", "")
    chrome_profile_directory = os.getenv("CHROME_PROFILE_DIRECTORY", "")

    worker_online = False
    if user_id:
        from .workers import worker_registry

        worker_online = worker_registry().get(user_id) is not None

    if worker_online:
        session_mode = "cdp"
        effective_chrome_user_data = ""
        mirror_path = None
        if fresh_profile:
            effective_chrome_profile = "Connect: fresh profile"
        elif chrome_user_data:
            profile_name = _chrome_profile_display_name_from_worker(
                user_id, chrome_user_data, chrome_profile_directory
            )
            effective_chrome_profile = (
                f"Connect: {profile_name}" if profile_name else "Connect: named profile"
            )
        else:
            effective_chrome_profile = "Connect: app default profile"
    else:
        session_mode = browser_session_mode(cdp_url=cdp_url, fresh_profile=fresh_profile)
        effective_chrome_user_data = resolve_chrome_user_data(
            chrome_user_data,
            fresh_profile=fresh_profile,
        )
        mirror_path = chrome_profile_mirror_path(chrome_user_data, chrome_profile_directory)
        if mirror_path:
            effective_chrome_profile = format_mirrored_chrome_profile(
                profile_directory=chrome_profile_directory,
                mirror_path=mirror_path,
                profile_name=_chrome_profile_display_name(chrome_user_data, chrome_profile_directory),
            )
        elif effective_chrome_user_data:
            effective_chrome_profile = format_effective_chrome_profile(
                effective_chrome_user_data,
                profile_directory=chrome_profile_directory,
            )
        else:
            effective_chrome_profile = ""

    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_set": api_key_set,
        "provider_keys_set": provider_keys_set,
        "provider_settings": provider_settings,
        "selected_models": selected_models,
        "cdp_port": int(os.getenv("CDP_PORT", "9222")),
        "cdp_url": "" if worker_online else cdp_url,
        "fresh_profile": fresh_profile,
        "chrome_user_data": chrome_user_data,
        "chrome_profile_directory": chrome_profile_directory,
        "chrome_profile_mirror_path": mirror_path,
        "effective_chrome_user_data": effective_chrome_user_data,
        "effective_chrome_profile": effective_chrome_profile,
        "default_chrome_user_data": default_chrome_user_data(),
        "browser_session_mode": session_mode,
        "connect_online": worker_online,
    }


def _chrome_profile_display_name_from_worker(
    user_id: str | None,
    user_data_dir: str,
    profile_directory: str,
) -> str:
    if not user_id:
        return ""
    from .workers import worker_registry

    for profile in worker_registry().profiles_for_user(user_id):
        if str(profile.get("user_data_dir") or "") == user_data_dir and (
            not profile_directory
            or str(profile.get("profile_directory") or "") == profile_directory
        ):
            return str(profile.get("name") or profile_directory or "")
    return profile_directory


def apply_config_update(update, user_id: str | None = None) -> dict:
    reload_runtime_env()
    settings_store = LlmSettingsStore()

    if user_id:
        current = UserLlmStore(user_id).load()
        provider = coerce_ui_provider(
            update.provider if update.provider is not None else current.provider
        )
    else:
        provider = coerce_ui_provider(
            update.provider if update.provider is not None else load_config().llm_provider
        )

    if update.base_url is not None or update.model is not None:
        settings_store.update_catalog(
            provider=provider,
            base_url=update.base_url,
            model=update.model,
        )

    coerced_model = None
    if update.model is not None:
        catalog = settings_store.ensure_loaded().get_provider(provider)
        coerced_model = coerce_provider_model(
            provider,
            update.model,
            base_url=update.base_url if update.base_url is not None else catalog.base_url,
        )

    llm_touch = (
        update.provider is not None
        or update.model is not None
        or update.api_key is not None
    )
    if user_id and llm_touch:
        UserLlmStore(user_id).update(
            provider=provider,
            model=coerced_model,
            api_key=update.api_key,
        )
    elif not user_id and llm_touch:
        if not ENV_FILE.exists():
            ENV_FILE.write_text("")
        if update.provider is not None:
            set_key(str(ENV_FILE), "LLM_PROVIDER", provider)
        if coerced_model is not None:
            set_key(str(ENV_FILE), provider_model_env_name(provider), coerced_model)
        if update.api_key is not None:
            key_env = provider_api_key_env_name(provider)
            if key_env:
                set_key(str(ENV_FILE), key_env, update.api_key)

    if not ENV_FILE.exists():
        ENV_FILE.write_text("")

    if update.base_url is not None:
        base_url_env = provider_base_url_env_name(provider)
        if base_url_env:
            set_key(
                str(ENV_FILE),
                base_url_env,
                coerce_provider_base_url(provider, update.base_url),
            )
    if update.fresh_profile is not None:
        set_key(str(ENV_FILE), "QA_FRESH_PROFILE", "true" if update.fresh_profile else "false")
    if update.chrome_user_data is not None:
        set_key(str(ENV_FILE), "CHROME_USER_DATA", update.chrome_user_data.strip())
    if update.chrome_profile_directory is not None:
        set_key(str(ENV_FILE), "CHROME_PROFILE_DIRECTORY", update.chrome_profile_directory.strip())
    if update.cdp_url is not None:
        set_key(str(ENV_FILE), "CDP_URL", update.cdp_url.strip())

    reload_runtime_env()
    return build_config_response(user_id=user_id)

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


def config_for_run(user_id: str | None = None) -> Config:
    reload_runtime_env()
    config = load_config()
    if user_id:
        prefs = UserLlmStore(user_id).load()
        return _apply_user_llm_to_config(config, prefs)

    settings = LlmSettingsStore().ensure_loaded()
    ui_provider = coerce_ui_provider(config.llm_provider)
    runtime = runtime_provider(ui_provider)
    catalog = settings.get_provider(ui_provider)
    config.llm_provider = runtime
    config.active_provider = ui_provider
    config.active_model = _active_model(config, ui_provider) or default_model_for_provider(ui_provider)
    if runtime == "groq":
        config.groq_model = config.active_model
        config.openai_base_url = catalog.base_url or default_base_url("groq")
    elif runtime == "google":
        config.google_model = config.active_model
        config.openai_base_url = catalog.base_url or default_base_url("google")
    elif runtime == "openrouter":
        config.openrouter_model = config.active_model
        config.openai_base_url = catalog.base_url or default_base_url("openrouter")
    else:
        config.ollama_model = config.active_model
        if ui_provider == "ollama-cloud":
            config.ollama_base_url = (
                config.ollama_cloud_base_url
                or catalog.base_url
                or default_base_url("ollama-cloud")
            )
            config.ollama_api_key = config.ollama_cloud_api_key
        else:
            if not config.ollama_base_url:
                config.ollama_base_url = catalog.base_url or default_base_url("ollama")
            config.ollama_api_key = ""
    return config


def _update_has_llm_fields(update) -> bool:
    if update is None:
        return False
    return any(
        getattr(update, field) is not None
        for field in ("provider", "base_url", "model", "api_key")
    )


def config_for_check(update=None, user_id: str | None = None) -> Config:
    """Build a Config for connection testing from saved settings or an optional form payload."""
    reload_runtime_env()
    settings = LlmSettingsStore().ensure_loaded()

    if not _update_has_llm_fields(update):
        return config_for_run(user_id=user_id)

    prefs = UserLlmStore(user_id).load() if user_id else None
    if prefs is not None:
        default_provider = prefs.provider
        default_model = prefs.selected_model(default_provider)
    else:
        config = load_config()
        default_provider = coerce_ui_provider(config.llm_provider)
        default_model = _active_model(config, default_provider)

    ui_provider = coerce_ui_provider(
        update.provider if update.provider is not None else default_provider
    )
    catalog = settings.get_provider(ui_provider)
    if update.base_url is not None:
        base_url = coerce_provider_base_url(ui_provider, update.base_url)
    else:
        base_url = coerce_provider_base_url(ui_provider, catalog.base_url)
    model = (
        coerce_provider_model(ui_provider, update.model, base_url=base_url)
        if update.model is not None
        else coerce_provider_model(
            ui_provider,
            (
                prefs.selected_model(ui_provider)
                if prefs is not None
                else default_model
            ),
            base_url=base_url,
        )
    )

    config = load_config()
    if prefs is not None:
        config = _apply_user_llm_to_config(config, prefs)

    runtime = runtime_provider(ui_provider)
    config.llm_provider = runtime
    config.active_provider = ui_provider
    config.active_model = model

    if update.api_key is not None:
        _apply_api_key_to_config(config, ui_provider, update.api_key)

    if runtime == "groq":
        config.groq_model = model
        config.openai_base_url = base_url or default_base_url("groq")
    elif runtime == "google":
        config.google_model = model
        config.openai_base_url = base_url or default_base_url("google")
    elif runtime == "openrouter":
        config.openrouter_model = model
        config.openai_base_url = base_url or default_base_url("openrouter")
    else:
        config.ollama_model = model
        config.ollama_base_url = base_url or default_base_url(ui_provider)
        if ui_provider == "ollama-cloud" and config.ollama_cloud_api_key:
            config.ollama_api_key = config.ollama_cloud_api_key
    return config


def check_llm_connection(update=None, user_id: str | None = None) -> None:
    config = config_for_check(update, user_id=user_id)
    from ..main import create_llm

    try:
        llm = create_llm(config)
        llm.chat([{"role": "user", "content": "Reply with OK only."}], temperature=0)
    except BaseException as exc:
        raise RuntimeError(format_llm_connection_error(exc)) from exc
