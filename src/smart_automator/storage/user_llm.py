"""Per-user LLM preferences (provider, models, API keys)."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..agents.roles import AGENT_ROLES, AgentRole
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
class RoleLlmSelection:
    provider: str = "groq"
    model: str = ""
    openrouter_provider: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "openrouter_provider": self.openrouter_provider,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RoleLlmSelection:
        if not isinstance(data, dict):
            return cls()
        provider = coerce_ui_provider(str(data.get("provider") or "groq"))
        model = str(data.get("model") or "").strip()
        openrouter_provider = str(data.get("openrouter_provider") or "").strip()
        if provider != "openrouter":
            openrouter_provider = ""
        if not model:
            model = default_model_for_provider(provider)
        return cls(
            provider=provider,
            model=model,
            openrouter_provider=openrouter_provider,
        )


@dataclass
class UserLlmPrefs:
    provider: str = "groq"
    models: dict[str, str] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)
    openrouter_provider: str = ""
    roles: dict[str, RoleLlmSelection] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        self.ensure_roles()
        return {
            "provider": self.provider,
            "models": dict(self.models),
            "api_keys": dict(self.api_keys),
            "openrouter_provider": self.openrouter_provider,
            "roles": {name: sel.to_dict() for name, sel in self.roles.items()},
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
        roles_raw = data.get("roles")
        roles: dict[str, RoleLlmSelection] = {}
        if isinstance(roles_raw, dict):
            for key, value in roles_raw.items():
                role = str(key).strip()
                if role in AGENT_ROLES:
                    roles[role] = RoleLlmSelection.from_dict(value)
        prefs = cls(
            provider=provider,
            models=models,
            api_keys=api_keys,
            openrouter_provider=openrouter_provider,
            roles=roles,
        )
        return prefs.ensure_roles()

    def ensure_roles(self) -> UserLlmPrefs:
        """Backfill role selections from legacy flat provider/model fields."""
        navigation_provider = coerce_ui_provider(self.provider)
        navigation_model = self.selected_model(navigation_provider)
        navigation_openrouter = (
            self.openrouter_provider if navigation_provider == "openrouter" else ""
        )

        if "navigation" not in self.roles:
            self.roles["navigation"] = RoleLlmSelection(
                provider=navigation_provider,
                model=navigation_model,
                openrouter_provider=navigation_openrouter,
            )
        else:
            nav = self.roles["navigation"]
            if not nav.model:
                nav.model = navigation_model

        if "planning" not in self.roles:
            planner_env = os.environ.get("PLANNER_LLM_PROVIDER", "").strip()
            if planner_env:
                planning_provider = coerce_ui_provider(planner_env)
            else:
                planning_provider = navigation_provider
            planner_model_env = os.environ.get("PLANNER_MODEL", "").strip()
            planning_model = (
                planner_model_env
                or self.models.get(planning_provider, "").strip()
                or default_model_for_provider(planning_provider)
            )
            planning_openrouter = (
                self.openrouter_provider if planning_provider == "openrouter" else ""
            )
            self.roles["planning"] = RoleLlmSelection(
                provider=planning_provider,
                model=planning_model,
                openrouter_provider=planning_openrouter,
            )

        # Keep navigation aliases in sync for legacy callers.
        nav = self.roles["navigation"]
        self.provider = nav.provider
        if nav.model:
            self.models[nav.provider] = nav.model
        if nav.provider == "openrouter":
            self.openrouter_provider = nav.openrouter_provider
        return self

    def role_selection(self, role: AgentRole | str) -> RoleLlmSelection:
        if role not in self.roles:
            self.ensure_roles()
        if role not in self.roles:
            self.roles[str(role)] = RoleLlmSelection()
        return self.roles[str(role)]

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
    navigation = RoleLlmSelection(
        provider=provider,
        model=models.get(provider, default_model_for_provider(provider)),
        openrouter_provider=openrouter_provider if provider == "openrouter" else "",
    )
    planner_env = os.environ.get("PLANNER_LLM_PROVIDER", "").strip()
    planning_provider = coerce_ui_provider(planner_env) if planner_env else provider
    planner_model = os.environ.get("PLANNER_MODEL", "").strip()
    if not planner_model:
        planner_model = models.get(planning_provider, default_model_for_provider(planning_provider))
    planning_openrouter = (
        openrouter_provider if planning_provider == "openrouter" else ""
    )
    return UserLlmPrefs(
        provider=provider,
        models=models,
        api_keys=api_keys,
        openrouter_provider=openrouter_provider,
        roles={
            "navigation": navigation,
            "planning": RoleLlmSelection(
                provider=planning_provider,
                model=planner_model,
                openrouter_provider=planning_openrouter,
            ),
        },
    )


def _prefs_from_row(row: UserLlmPrefsRow) -> UserLlmPrefs:
    return UserLlmPrefs.from_dict(
        {
            "provider": row.provider,
            "models": row.models,
            "api_keys": row.api_keys,
            "openrouter_provider": row.openrouter_provider,
            "roles": row.roles or {},
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
        roles={name: sel.to_dict() for name, sel in cleaned.roles.items()},
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
                    row.roles = {name: sel.to_dict() for name, sel in cleaned.roles.items()}
            return cleaned

    def update(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        openrouter_provider: str | None = None,
        role: AgentRole | str | None = None,
        roles: dict[str, dict[str, str | None]] | None = None,
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

                prefs.ensure_roles()

                if roles:
                    for role_name, payload in roles.items():
                        if role_name not in AGENT_ROLES or not isinstance(payload, dict):
                            continue
                        selection = prefs.role_selection(role_name)
                        if payload.get("provider") is not None:
                            selection.provider = coerce_ui_provider(str(payload["provider"]))
                        if payload.get("model") is not None:
                            name = str(payload["model"]).strip()
                            if name:
                                selection.model = name
                                prefs.models[selection.provider] = name
                        if payload.get("openrouter_provider") is not None:
                            if selection.provider == "openrouter":
                                selection.openrouter_provider = str(
                                    payload["openrouter_provider"] or ""
                                ).strip()
                            else:
                                selection.openrouter_provider = ""
                        if payload.get("api_key") is not None:
                            token = str(payload["api_key"]).strip()
                            active = selection.provider
                            if token:
                                prefs.api_keys[active] = token

                target_role = str(role or "navigation")
                if provider is not None or model is not None or openrouter_provider is not None:
                    selection = prefs.role_selection(target_role)
                    if provider is not None:
                        selection.provider = coerce_ui_provider(provider)
                    active = selection.provider
                    if model is not None:
                        name = model.strip()
                        if name:
                            selection.model = name
                            prefs.models[active] = name
                    if api_key is not None:
                        token = api_key.strip()
                        if token:
                            prefs.api_keys[active] = token
                    if openrouter_provider is not None:
                        if active == "openrouter":
                            selection.openrouter_provider = openrouter_provider.strip()
                        else:
                            selection.openrouter_provider = ""
                elif api_key is not None:
                    active = prefs.role_selection(target_role).provider
                    token = api_key.strip()
                    if token:
                        prefs.api_keys[active] = token

                cleaned = UserLlmPrefs.from_dict(prefs.to_dict())
                if row is None:
                    session.add(_row_from_prefs(self._user_id, cleaned))
                else:
                    row.provider = cleaned.provider
                    row.models = cleaned.models
                    row.api_keys = cleaned.api_keys
                    row.openrouter_provider = cleaned.openrouter_provider
                    row.roles = {name: sel.to_dict() for name, sel in cleaned.roles.items()}
            return cleaned
