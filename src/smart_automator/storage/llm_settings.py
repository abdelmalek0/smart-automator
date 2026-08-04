from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import set_key

from ..server.paths import ENV_FILE, LLM_SETTINGS_FILE
from ..server.provider_utils import (
    UI_PROVIDERS,
    coerce_provider_base_url,
    coerce_provider_model,
    default_base_url,
    default_model_for_provider,
    is_cloud_ollama_model,
    normalize_provider,
    provider_base_url_env_name,
    provider_model_env_name,
    runtime_provider,
)

_MAX_MODELS_PER_PROVIDER = 50


@dataclass
class ProviderSettings:
    base_url: str = ""
    models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "models": list(self.models),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, provider: str) -> ProviderSettings:
        if not data:
            default_model = default_model_for_provider(provider)
            return cls(
                base_url=default_base_url(provider),
                models=[default_model],
            )
        models_raw = data.get("models")
        models = (
            [str(m) for m in models_raw if str(m).strip()]
            if isinstance(models_raw, list)
            else []
        )
        legacy_model = str(data.get("model") or "").strip()
        if legacy_model and legacy_model not in models:
            models.insert(0, legacy_model)
        base_url = str(data.get("base_url") or "").strip() or default_base_url(provider)
        base_url = coerce_provider_base_url(provider, base_url)
        coerced_models: list[str] = []
        for name in models:
            coerced = coerce_provider_model(provider, name, base_url=base_url)
            if coerced and coerced not in coerced_models:
                coerced_models.append(coerced)
        if not coerced_models:
            coerced_models = [default_model_for_provider(provider)]
        return cls(base_url=base_url, models=coerced_models)


@dataclass
class LlmSettings:
    providers: dict[str, ProviderSettings] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": {
                name: settings.to_dict() for name, settings in self.providers.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LlmSettings:
        raw_providers = data.get("providers")
        providers: dict[str, ProviderSettings] = {}
        if isinstance(raw_providers, dict):
            for key, value in raw_providers.items():
                canonical = normalize_provider(str(key))
                if isinstance(value, dict):
                    providers[canonical] = ProviderSettings.from_dict(value, provider=canonical)
        return cls(providers=providers)

    def get_provider(self, provider: str) -> ProviderSettings:
        canonical = normalize_provider(provider)
        if canonical not in self.providers:
            self.providers[canonical] = ProviderSettings.from_dict(None, provider=canonical)
        return self.providers[canonical]

    def sanitize_providers(self) -> bool:
        """Coerce each provider slot to valid base_url/model combos. Returns True if changed."""
        changed = False
        for provider in UI_PROVIDERS:
            entry = self.get_provider(provider)
            coerced_url = coerce_provider_base_url(provider, entry.base_url)
            if coerced_url != entry.base_url:
                entry.base_url = coerced_url
                changed = True
            models = [
                m
                for m in entry.models
                if not (
                    normalize_provider(provider) == "ollama" and is_cloud_ollama_model(m)
                )
            ]
            coerced_models: list[str] = []
            for name in models:
                coerced = coerce_provider_model(provider, name, base_url=coerced_url)
                if coerced and coerced not in coerced_models:
                    coerced_models.append(coerced)
            if not coerced_models:
                coerced_models = [default_model_for_provider(provider)]
            if coerced_models != entry.models:
                entry.models = coerced_models
                changed = True
        return changed


def _is_legacy_format(raw: dict[str, Any]) -> bool:
    if "provider" in raw:
        return True
    providers = raw.get("providers")
    if isinstance(providers, dict):
        for value in providers.values():
            if isinstance(value, dict) and "model" in value:
                return True
    return False


def _legacy_ui_provider(raw: dict[str, Any]) -> str:
    provider = normalize_provider(str(raw.get("provider") or "groq"))
    providers = raw.get("providers")
    if isinstance(providers, dict):
        entry = providers.get(provider)
        if isinstance(entry, dict):
            base_url = str(entry.get("base_url") or "")
            if runtime_provider(provider) == "ollama" and "ollama.com" in base_url.lower():
                return "ollama-cloud"
    return provider


def _legacy_model_for_provider(raw: dict[str, Any], provider: str) -> str:
    providers = raw.get("providers")
    if isinstance(providers, dict):
        entry = providers.get(provider)
        if isinstance(entry, dict):
            model = str(entry.get("model") or "").strip()
            if model:
                return model
    return default_model_for_provider(provider)


class LlmSettingsStore:
    def __init__(self, path: Path = LLM_SETTINGS_FILE) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _load_raw(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_raw(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    def _migrate_legacy_to_env(self, raw: dict[str, Any]) -> None:
        if not _is_legacy_format(raw):
            return
        if not ENV_FILE.exists():
            ENV_FILE.write_text("")
        ui_provider = _legacy_ui_provider(raw)
        if not os.environ.get("LLM_PROVIDER", "").strip():
            set_key(str(ENV_FILE), "LLM_PROVIDER", ui_provider)
        legacy_model = _legacy_model_for_provider(raw, ui_provider)
        model_env = provider_model_env_name(ui_provider)
        if not os.environ.get(model_env, "").strip():
            set_key(str(ENV_FILE), model_env, legacy_model)
        base_url_env = provider_base_url_env_name(ui_provider)
        if base_url_env and not os.environ.get(base_url_env, "").strip():
            entry = raw.get("providers", {}).get(ui_provider, {})
            if isinstance(entry, dict):
                base_url = str(entry.get("base_url") or "").strip()
                if base_url:
                    set_key(str(ENV_FILE), base_url_env, base_url)

    def load(self) -> LlmSettings:
        with self._lock:
            raw = self._load_raw()
            if _is_legacy_format(raw):
                self._migrate_legacy_to_env(raw)
            settings = LlmSettings.from_dict(raw)
        for provider in UI_PROVIDERS:
            settings.get_provider(provider)
        changed = settings.sanitize_providers()
        if _is_legacy_format(raw) or changed:
            self.save(settings)
        return settings

    def save(self, settings: LlmSettings) -> None:
        with self._lock:
            self._save_raw(settings.to_dict())

    def update_catalog(
        self,
        *,
        provider: str,
        base_url: str | None = None,
        model: str | None = None,
    ) -> LlmSettings:
        with self._lock:
            settings = LlmSettings.from_dict(self._load_raw())
            canonical = normalize_provider(provider)
            entry = settings.get_provider(canonical)
            if base_url is not None:
                entry.base_url = coerce_provider_base_url(
                    canonical,
                    base_url.strip() or default_base_url(canonical),
                )
            if model is not None:
                name = model.strip()
                if name:
                    coerced_model = coerce_provider_model(
                        canonical,
                        name,
                        base_url=entry.base_url,
                    )
                    models = [m for m in entry.models if m != coerced_model]
                    models.insert(0, coerced_model)
                    entry.models = models[:_MAX_MODELS_PER_PROVIDER]
            settings.sanitize_providers()
            self._save_raw(settings.to_dict())
            return settings

    def seed_from_env(self) -> LlmSettings:
        env_provider = os.environ.get("LLM_PROVIDER", "groq")
        provider = normalize_provider(env_provider)
        if provider == "ollama-cloud":
            model = os.environ.get("OLLAMA_CLOUD_MODEL", "")
            base_url = os.environ.get("OLLAMA_CLOUD_BASE_URL", default_base_url("ollama-cloud"))
        elif provider == "ollama":
            model = os.environ.get("OLLAMA_MODEL", "")
            base_url = os.environ.get("OLLAMA_BASE_URL", default_base_url("ollama"))
        elif runtime_provider(provider) == "groq":
            model = os.environ.get("GROQ_MODEL", "")
            base_url = default_base_url(provider)
        elif runtime_provider(provider) == "google":
            model = os.environ.get("GOOGLE_MODEL", "")
            base_url = default_base_url(provider)
        elif runtime_provider(provider) == "openrouter":
            model = os.environ.get("OPENROUTER_MODEL", "")
            base_url = default_base_url(provider)
        else:
            model = ""
            base_url = default_base_url(provider)
        model = model.strip() or default_model_for_provider(provider)
        settings = LlmSettings()
        for known in UI_PROVIDERS:
            entry = settings.get_provider(known)
            if known == provider:
                entry.base_url = base_url.rstrip("/")
                entry.models = [model]
        self.save(settings)
        return settings

    def ensure_loaded(self) -> LlmSettings:
        if not self._path.exists():
            return self.seed_from_env()
        return self.load()
