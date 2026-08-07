"""Per-user LLM preferences (provider, models, API keys)."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..server import paths as server_paths
from ..server.provider_utils import (
    UI_PROVIDERS,
    coerce_ui_provider,
    default_model_for_provider,
    normalize_provider,
    provider_api_key_env_name,
    provider_model_env_name,
)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


@dataclass
class UserLlmPrefs:
    provider: str = "groq"
    models: dict[str, str] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "models": dict(self.models),
            "api_keys": dict(self.api_keys),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UserLlmPrefs:
        if not isinstance(data, dict):
            return cls()
        provider = coerce_ui_provider(str(data.get("provider") or "groq"))
        models_raw = data.get("models")
        models: dict[str, str] = {}
        if isinstance(models_raw, dict):
            for key, value in models_raw.items():
                canonical = normalize_provider(str(key))
                name = str(value or "").strip()
                if name:
                    models[canonical] = name
        keys_raw = data.get("api_keys")
        api_keys: dict[str, str] = {}
        if isinstance(keys_raw, dict):
            for key, value in keys_raw.items():
                canonical = normalize_provider(str(key))
                token = str(value or "").strip()
                if token and canonical in UI_PROVIDERS:
                    api_keys[canonical] = token
        return cls(provider=provider, models=models, api_keys=api_keys)

    def selected_model(self, provider: str | None = None) -> str:
        canonical = coerce_ui_provider(provider or self.provider)
        stored = (self.models.get(canonical) or "").strip()
        if stored:
            return stored
        return default_model_for_provider(canonical)

    def api_key_for(self, provider: str) -> str:
        canonical = normalize_provider(provider)
        return (self.api_keys.get(canonical) or "").strip()

    def api_key_is_set(self, provider: str) -> bool:
        return bool(self.api_key_for(provider))


def _seed_prefs_from_env() -> UserLlmPrefs:
    provider = coerce_ui_provider(os.environ.get("LLM_PROVIDER", "groq"))
    models: dict[str, str] = {}
    api_keys: dict[str, str] = {}
    for name in UI_PROVIDERS:
        model_env = provider_model_env_name(name)
        model = os.environ.get(model_env, "").strip()
        if model:
            models[name] = model
        key_env = provider_api_key_env_name(name)
        if key_env:
            token = os.environ.get(key_env, "").strip()
            if token:
                api_keys[name] = token
    if provider not in models:
        models[provider] = default_model_for_provider(provider)
    return UserLlmPrefs(provider=provider, models=models, api_keys=api_keys)


class UserLlmStore:
    def __init__(self, user_id: str, path: Path | None = None) -> None:
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id is required")
        self._user_id = str(user_id).strip()
        self._dir = server_paths.LLM_USER_DIR
        self._path = path or (self._dir / f"{self._user_id}.json")
        self._lock = threading.Lock()

    def _other_prefs_exist(self) -> bool:
        try:
            for item in self._dir.glob("*.json"):
                if item.resolve() != self._path.resolve():
                    return True
        except OSError:
            return False
        return False

    def _load_raw(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_raw(self, data: dict[str, Any]) -> None:
        _atomic_write_json(self._path, data)

    def load(self) -> UserLlmPrefs:
        with self._lock:
            raw = self._load_raw()
            if raw:
                return UserLlmPrefs.from_dict(raw)
            if not self._other_prefs_exist():
                seeded = _seed_prefs_from_env()
                self._save_raw(seeded.to_dict())
                return seeded
            return UserLlmPrefs()

    def save(self, prefs: UserLlmPrefs) -> UserLlmPrefs:
        with self._lock:
            cleaned = UserLlmPrefs.from_dict(prefs.to_dict())
            self._save_raw(cleaned.to_dict())
            return cleaned

    def update(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> UserLlmPrefs:
        with self._lock:
            raw = self._load_raw()
            if raw:
                prefs = UserLlmPrefs.from_dict(raw)
            elif not self._other_prefs_exist():
                prefs = _seed_prefs_from_env()
            else:
                prefs = UserLlmPrefs()

            if provider is not None:
                prefs.provider = coerce_ui_provider(provider)
            active = prefs.provider
            if model is not None:
                name = model.strip()
                if name:
                    prefs.models[active] = name
            if api_key is not None:
                token = api_key.strip()
                if token:
                    prefs.api_keys[active] = token
            cleaned = UserLlmPrefs.from_dict(prefs.to_dict())
            self._save_raw(cleaned.to_dict())
            return cleaned
