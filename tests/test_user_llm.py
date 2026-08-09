"""Tests for per-user LLM preferences."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from smart_automator.config import Config
from smart_automator.db.engine import get_engine
from smart_automator.db.models import Base
from smart_automator.db import reset_engine
from smart_automator.server.config_service import (
    apply_config_update,
    config_for_run,
)
from smart_automator.server.models import ConfigUpdate
from smart_automator.storage.user_llm import UserLlmPrefs, UserLlmStore


def _setup_isolated_db(tmp: str) -> None:
    reset_engine(f"sqlite:///{tmp}/test.db")
    Base.metadata.create_all(get_engine())


class TestUserLlmStore(unittest.TestCase):
    def test_isolation_between_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            a = UserLlmStore("user-a")
            b = UserLlmStore("user-b")
            a.update(provider="groq", model="model-a", api_key="key-a")
            b.update(provider="openrouter", model="model-b", api_key="key-b")

            prefs_a = a.load()
            prefs_b = b.load()
            self.assertEqual(prefs_a.provider, "groq")
            self.assertEqual(prefs_a.api_key_for("groq"), "key-a")
            self.assertEqual(prefs_b.provider, "openrouter")
            self.assertEqual(prefs_b.api_key_for("openrouter"), "key-b")
            self.assertFalse(prefs_b.api_key_is_set("groq"))

    def test_first_user_seeds_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            with patch.dict(
                os.environ,
                {
                    "LLM_PROVIDER": "openrouter",
                    "OPENROUTER_MODEL": "seed-model",
                    "OPENROUTER_API_KEY": "seed-key",
                },
                clear=False,
            ):
                prefs = UserLlmStore("first-user").load()
            self.assertEqual(prefs.provider, "openrouter")
            self.assertEqual(prefs.selected_model("openrouter"), "seed-model")
            self.assertEqual(prefs.api_key_for("openrouter"), "seed-key")

    def test_second_user_does_not_inherit_env_after_first_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            with patch.dict(
                os.environ,
                {
                    "LLM_PROVIDER": "groq",
                    "GROQ_API_KEY": "shared-key",
                    "GROQ_MODEL": "shared-model",
                },
                clear=False,
            ):
                first = UserLlmStore("user-1").load()
                second = UserLlmStore("user-2").load()
            self.assertTrue(first.api_key_is_set("groq"))
            self.assertFalse(second.api_key_is_set("groq"))
            self.assertEqual(second.provider, "groq")

    def test_coerce_legacy_ollama_provider(self):
        prefs = UserLlmPrefs.from_dict({"provider": "ollama", "models": {}, "api_keys": {}})
        self.assertEqual(prefs.provider, "groq")

    def test_openrouter_provider_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            store = UserLlmStore("u-or")
            store.update(
                provider="openrouter",
                model="deepseek/deepseek-v4-flash-0731",
                openrouter_provider="together",
            )
            prefs = store.load()
            self.assertEqual(prefs.openrouter_provider, "together")
            store.update(provider="openrouter", openrouter_provider="")
            cleared = store.load()
            self.assertEqual(cleared.openrouter_provider, "")

    def test_role_selection_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            store = UserLlmStore("role-user")
            store.update(
                roles={
                    "navigation": {
                        "provider": "groq",
                        "model": "nav-model",
                    },
                    "planning": {
                        "provider": "google",
                        "model": "plan-model",
                    },
                }
            )
            prefs = store.load()
            self.assertEqual(prefs.role_selection("navigation").provider, "groq")
            self.assertEqual(prefs.role_selection("navigation").model, "nav-model")
            self.assertEqual(prefs.role_selection("planning").provider, "google")
            self.assertEqual(prefs.role_selection("planning").model, "plan-model")

    def test_legacy_prefs_seed_both_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            store = UserLlmStore("legacy-user")
            store.save(
                UserLlmPrefs(
                    provider="groq",
                    models={"groq": "legacy-model"},
                    api_keys={"groq": "legacy-key"},
                )
            )
            prefs = store.load()
            self.assertEqual(prefs.role_selection("navigation").model, "legacy-model")
            self.assertEqual(prefs.role_selection("planning").provider, "groq")
            self.assertEqual(prefs.role_selection("planning").model, "legacy-model")

        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            store = UserLlmStore("u-groq")
            store.update(provider="groq", openrouter_provider="together")
            prefs = store.load()
            self.assertEqual(prefs.openrouter_provider, "")


class TestPerUserConfigService(unittest.TestCase):
    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_config_for_run_uses_user_prefs(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config(
            llm_provider="groq",
            groq_model="env-model",
            groq_api_key="env-key",
            openrouter_api_key="env-openrouter-key",
        )
        catalog = MagicMock()
        catalog.base_url = "https://openrouter.ai/api/v1"
        catalog.models = ["user-model"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            UserLlmStore("other").save(UserLlmPrefs(provider="groq"))
            UserLlmStore("u1").save(
                UserLlmPrefs(
                    provider="openrouter",
                    models={"openrouter": "user-model"},
                    api_keys={"openrouter": "user-key"},
                    openrouter_provider="fireworks",
                )
            )
            config = config_for_run("u1")

        self.assertEqual(config.active_provider, "openrouter")
        self.assertEqual(config.active_model, "user-model")
        self.assertEqual(config.planner_model, "user-model")
        self.assertEqual(config.active_planning_provider, "openrouter")
        self.assertEqual(config.openrouter_api_key, "user-key")
        self.assertEqual(config.openrouter_provider, "fireworks")
        self.assertEqual(config.groq_api_key, "")
        self.assertEqual(config.openai_base_url, "https://openrouter.ai/api/v1")

    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_config_for_run_does_not_leak_env_keys_when_user_has_none(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config(
            llm_provider="groq",
            groq_api_key="env-key",
            openrouter_api_key="env-openrouter",
        )
        catalog = MagicMock()
        catalog.base_url = "https://api.groq.com/openai/v1"
        catalog.models = ["m"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            UserLlmStore("other").save(UserLlmPrefs(provider="groq", api_keys={"groq": "other"}))
            UserLlmStore("empty-user").save(
                UserLlmPrefs(provider="groq", models={"groq": "m"}, api_keys={})
            )
            config = config_for_run("empty-user")

        self.assertEqual(config.groq_api_key, "")
        self.assertEqual(config.openrouter_api_key, "")

    @patch("smart_automator.server.config_service.build_config_response")
    @patch("smart_automator.server.config_service.set_key")
    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    @patch("smart_automator.server.config_service.ENV_FILE")
    def test_apply_config_update_writes_user_prefs_not_env_keys(
        self,
        env_file_mock,
        _reload,
        load_config_mock,
        store_mock,
        set_key_mock,
        _build_response,
    ):
        env_file_mock.exists.return_value = True
        load_config_mock.return_value = Config(llm_provider="groq")
        catalog = MagicMock()
        catalog.base_url = "https://api.groq.com/openai/v1"
        catalog.models = ["m1"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        with tempfile.TemporaryDirectory() as tmp:
            _setup_isolated_db(tmp)
            apply_config_update(
                ConfigUpdate(
                    provider="groq",
                    model="m1",
                    api_key="secret-user-key",
                ),
                user_id="alice",
            )
            prefs = UserLlmStore("alice").load()

        self.assertEqual(prefs.api_key_for("groq"), "secret-user-key")
        self.assertFalse(
            any(call.args[1] == "GROQ_API_KEY" for call in set_key_mock.call_args_list)
        )
        self.assertFalse(
            any(call.args[1] == "LLM_PROVIDER" for call in set_key_mock.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
