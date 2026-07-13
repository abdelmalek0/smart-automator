from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..server.paths import LLM_SETTINGS_FILE
from ..server.provider_utils import (
    UI_PROVIDERS,
    default_base_url,
    default_model_for_provider,
    normalize_provider,
    runtime_provider,
)

_MAX_MODELS_PER_PROVIDER = 50


@dataclass
class ProviderSettings:
    base_url: str = ""
    model: str = ""
    models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "models": list(self.models),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, provider: str) -> ProviderSettings:
        if not data:
            return cls(
                base_url=default_base_url(provider),
                model=default_model_for_provider(provider),
                models=[default_model_for_provider(provider)],
            )
        models_raw = data.get("models")
        models = (
            [str(m) for m in models_raw if str(m).strip()]
            if isinstance(models_raw, list)
            else []
        )
        model = str(data.get("model") or "").strip() or default_model_for_provider(provider)
        if model and model not in models:
            models.insert(0, model)
        if not models:
            models = [model]
        base_url = str(data.get("base_url") or "").strip() or default_base_url(provider)
        return cls(base_url=base_url, model=model, models=models)


@dataclass
class LlmSettings:
    provider: str = "groq"
    providers: dict[str, ProviderSettings] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "providers": {
                name: settings.to_dict() for name, settings in self.providers.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LlmSettings:
        provider = normalize_provider(str(data.get("provider") or "groq"))
        raw_providers = data.get("providers")
        providers: dict[str, ProviderSettings] = {}
        if isinstance(raw_providers, dict):
            for key, value in raw_providers.items():
                canonical = normalize_provider(str(key))
                if isinstance(value, dict):
                    providers[canonical] = ProviderSettings.from_dict(value, provider=canonical)
        return cls(provider=provider, providers=providers)

    def get_provider(self, provider: str | None = None) -> ProviderSettings:
        canonical = normalize_provider(provider or self.provider)
        if canonical not in self.providers:
            self.providers[canonical] = ProviderSettings.from_dict(None, provider=canonical)
        return self.providers[canonical]


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

    def load(self) -> LlmSettings:
        with self._lock:
            settings = LlmSettings.from_dict(self._load_raw())
        for provider in UI_PROVIDERS:
            settings.get_provider(provider)
        return settings

    def save(self, settings: LlmSettings) -> None:
        with self._lock:
            self._save_raw(settings.to_dict())

    def update_active(
        self,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> LlmSettings:
        with self._lock:
            settings = LlmSettings.from_dict(self._load_raw())
            if provider is not None:
                settings.provider = normalize_provider(provider)
            entry = settings.get_provider(settings.provider)
            if base_url is not None:
                entry.base_url = base_url.strip() or default_base_url(settings.provider)
            if model is not None:
                name = model.strip()
                if name:
                    entry.model = name
                    models = [m for m in entry.models if m != name]
                    models.insert(0, name)
                    entry.models = models[:_MAX_MODELS_PER_PROVIDER]
            self._save_raw(settings.to_dict())
            return settings

    def seed_from_env(self) -> LlmSettings:
        env_provider = os.environ.get("LLM_PROVIDER", "groq")
        runtime = runtime_provider(env_provider)
        if runtime == "groq":
            model = os.environ.get("GROQ_MODEL", "")
        elif runtime == "google":
            model = os.environ.get("GOOGLE_MODEL", "")
        else:
            model = os.environ.get("OLLAMA_MODEL", "")
        base_url = (
            os.environ.get("OLLAMA_BASE_URL", default_base_url(env_provider))
            if runtime == "ollama"
            else default_base_url(env_provider)
        )
        if runtime == "ollama" and "ollama.com" in base_url.lower():
            provider = "ollama-cloud"
        else:
            provider = normalize_provider(env_provider)
        model = model.strip() or default_model_for_provider(provider)
        settings = LlmSettings(provider=provider)
        for known in UI_PROVIDERS:
            entry = settings.get_provider(known)
            if known == provider:
                entry.base_url = base_url.rstrip("/")
                entry.model = model
                entry.models = [model]
        self.save(settings)
        return settings

    def ensure_loaded(self) -> LlmSettings:
        if not self._path.exists():
            return self.seed_from_env()
        return self.load()
