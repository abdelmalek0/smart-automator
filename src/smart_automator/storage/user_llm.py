"""Per-user LLM preferences (provider, models, API keys)."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..db.engine import get_session
from ..db.models import UserLlmPrefsRow
from ..server.provider_utils import (
    UI_PROVIDERS,
    coerce_ui_provider,
    default_model_for_provider,
    normalize_provider,
    provider_api_key_env_name,
    provider_model_env_name,
)


@dataclass
class UserLlmPrefs:
    provider: str = "groq"
    models: dict[str, str] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)
    openrouter_provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "models": dict(self.models),
            "api_keys": dict(self.api_keys),
            "openrouter_provider": self.openrouter_provider,
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
        openrouter_provider = str(data.get("openrouter_provider") or "").strip()
        return cls(
            provider=provider,
            models=models,
            api_keys=api_keys,
            openrouter_provider=openrouter_provider,
        )

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
    openrouter_provider = os.environ.get("OPENROUTER_PROVIDER", "").strip()
    return UserLlmPrefs(
        provider=provider,
        models=models,
        api_keys=api_keys,
        openrouter_provider=openrouter_provider,
    )


def _prefs_from_row(row: UserLlmPrefsRow) -> UserLlmPrefs:
    return UserLlmPrefs.from_dict(
        {
            "provider": row.provider,
            "models": row.models,
            "api_keys": row.api_keys,
            "openrouter_provider": row.openrouter_provider,
        }
    )


def _row_from_prefs(user_id: str, prefs: UserLlmPrefs) -> UserLlmPrefsRow:
    cleaned = UserLlmPrefs.from_dict(prefs.to_dict())
    return UserLlmPrefsRow(
        user_id=user_id,
        provider=cleaned.provider,
        models=cleaned.models,
        api_keys=cleaned.api_keys,
        openrouter_provider=cleaned.openrouter_provider,
    )


class UserLlmStore:
    def __init__(self, user_id: str, path: Path | None = None) -> None:
        # path is ignored; kept for backward compatibility with tests.
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id is required")
        self._user_id = str(user_id).strip()
        self._lock = threading.Lock()

    def load(self) -> UserLlmPrefs:
        with self._lock:
            with get_session() as session:
                row = session.get(UserLlmPrefsRow, self._user_id)
                if row is not None:
                    return _prefs_from_row(row)
                other_exists = session.scalar(
                    select(UserLlmPrefsRow.user_id)
                    .where(UserLlmPrefsRow.user_id != self._user_id)
                    .limit(1)
                ) is not None
            if not other_exists:
                seeded = _seed_prefs_from_env()
                cleaned = UserLlmPrefs.from_dict(seeded.to_dict())
                with get_session() as session:
                    session.add(_row_from_prefs(self._user_id, cleaned))
                return cleaned
            return UserLlmPrefs()

    def save(self, prefs: UserLlmPrefs) -> UserLlmPrefs:
        with self._lock:
            cleaned = UserLlmPrefs.from_dict(prefs.to_dict())
            with get_session() as session:
                row = session.get(UserLlmPrefsRow, self._user_id)
                if row is None:
                    session.add(_row_from_prefs(self._user_id, cleaned))
                else:
                    row.provider = cleaned.provider
                    row.models = cleaned.models
                    row.api_keys = cleaned.api_keys
                    row.openrouter_provider = cleaned.openrouter_provider
            return cleaned

    def update(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        openrouter_provider: str | None = None,
    ) -> UserLlmPrefs:
        with self._lock:
            with get_session() as session:
                row = session.get(UserLlmPrefsRow, self._user_id)
                other_exists = session.scalar(
                    select(UserLlmPrefsRow.user_id)
                    .where(UserLlmPrefsRow.user_id != self._user_id)
                    .limit(1)
                ) is not None
                if row is not None:
                    prefs = _prefs_from_row(row)
                elif not other_exists:
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
                if openrouter_provider is not None and active == "openrouter":
                    prefs.openrouter_provider = openrouter_provider.strip()
                cleaned = UserLlmPrefs.from_dict(prefs.to_dict())
                if row is None:
                    session.add(_row_from_prefs(self._user_id, cleaned))
                else:
                    row.provider = cleaned.provider
                    row.models = cleaned.models
                    row.api_keys = cleaned.api_keys
                    row.openrouter_provider = cleaned.openrouter_provider
            return cleaned
