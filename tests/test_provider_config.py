import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from smart_automator.config import Config
from smart_automator.llm.groq import OpenAICompatLLM
from smart_automator.llm.ollama import OllamaLLM
from smart_automator.main import create_llm
from smart_automator.server.config_service import (
    apply_config_update,
    config_for_check,
    config_for_run,
    migrate_legacy_ollama_env,
)
from smart_automator.server.models import ConfigUpdate
from smart_automator.server.provider_utils import (
    UI_PROVIDERS,
    coerce_provider_base_url,
    coerce_provider_model,
    coerce_ui_provider,
    default_base_url,
    default_model_for_provider,
    format_llm_connection_error,
    is_ollama_cloud_url,
    normalize_provider,
    runtime_provider,
)
from smart_automator.storage.llm_settings import LlmSettingsStore


class TestOpenRouterProvider(unittest.TestCase):
    def test_normalize_and_runtime(self):
        self.assertEqual(normalize_provider("openrouter"), "openrouter")
        self.assertEqual(runtime_provider("openrouter"), "openrouter")
        self.assertEqual(
            default_base_url("openrouter"),
            "https://openrouter.ai/api/v1",
        )
        self.assertEqual(
            default_model_for_provider("openrouter"),
            "deepseek/deepseek-v4-flash-0731",
        )

    def test_ui_providers_exclude_local_ollama(self):
        self.assertNotIn("ollama", UI_PROVIDERS)
        self.assertIn("ollama-cloud", UI_PROVIDERS)
        self.assertEqual(coerce_ui_provider("ollama"), "groq")
        self.assertEqual(coerce_ui_provider("ollama-cloud"), "ollama-cloud")

    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_config_for_run_openrouter(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config(
            llm_provider="openrouter",
            openrouter_model="deepseek/deepseek-v4-flash-0731",
            openrouter_api_key="sk-or-test",
        )
        catalog = MagicMock()
        catalog.base_url = "https://openrouter.ai/api/v1"
        catalog.models = ["deepseek/deepseek-v4-flash-0731"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        config = config_for_run()

        self.assertEqual(config.llm_provider, "openrouter")
        self.assertEqual(config.active_provider, "openrouter")
        self.assertEqual(config.active_model, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(config.openrouter_model, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(config.openai_base_url, "https://openrouter.ai/api/v1")

    def test_create_llm_openrouter(self):
        config = Config(
            llm_provider="openrouter",
            openrouter_api_key="sk-or-test",
            openrouter_model="deepseek/deepseek-v4-flash-0731",
            openai_base_url="https://openrouter.ai/api/v1",
            active_model="deepseek/deepseek-v4-flash-0731",
        )
        llm = create_llm(config, "openrouter")
        self.assertIsInstance(llm, OpenAICompatLLM)
        self.assertEqual(llm.model_name, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(llm._provider, "openrouter")
        headers = llm._headers()
        self.assertEqual(headers["Authorization"], "Bearer sk-or-test")
        self.assertEqual(headers["X-Title"], "smart-automator")
        self.assertIn("HTTP-Referer", headers)

    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_config_for_check_openrouter_api_key(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config()
        catalog = MagicMock()
        catalog.base_url = "https://openrouter.ai/api/v1"
        catalog.models = ["deepseek/deepseek-v4-flash-0731"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        update = ConfigUpdate(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model="deepseek/deepseek-v4-flash-0731",
            api_key="sk-or-form",
        )
        config = config_for_check(update)

        self.assertEqual(config.llm_provider, "openrouter")
        self.assertEqual(config.active_provider, "openrouter")
        self.assertEqual(config.openrouter_model, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(config.openrouter_api_key, "sk-or-form")
        self.assertEqual(config.openai_base_url, "https://openrouter.ai/api/v1")


class TestProviderCoercion(unittest.TestCase):
    def test_local_ollama_rejects_cloud_url(self):
        url = coerce_provider_base_url("ollama", "https://ollama.com")
        self.assertEqual(url, "http://localhost:11434")

    def test_cloud_ollama_rejects_local_url(self):
        url = coerce_provider_base_url("ollama-cloud", "http://localhost:11434")
        self.assertEqual(url, "https://ollama.com")

    def test_local_ollama_rejects_cloud_model(self):
        model = coerce_provider_model(
            "ollama",
            "gemma4:31b-cloud",
            base_url="http://localhost:11434",
        )
        self.assertEqual(model, "llama3.2")

    def test_format_ollama_cloud_403(self):
        request = MagicMock()
        request.url = "https://ollama.com/api/chat"
        error = httpx.HTTPStatusError(
            "403",
            request=request,
            response=MagicMock(status_code=403),
        )
        message = format_llm_connection_error(error)
        self.assertIn("Ollama Cloud returned 403 Forbidden", message)
        self.assertIn("OLLAMA_CLOUD_API_KEY", message)


class TestLlmSettingsMigration(unittest.TestCase):
    def test_load_migrates_contaminated_local_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "provider": "ollama",
                        "providers": {
                            "ollama": {
                                "base_url": "https://ollama.com",
                                "model": "gemma4:31b-cloud",
                                "models": ["gemma4:31b-cloud", "llama3.2"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = LlmSettingsStore(path=path)
            settings = store.load()
            entry = settings.get_provider("ollama")
            self.assertEqual(entry.base_url, "http://localhost:11434")
            self.assertEqual(entry.models[0], "llama3.2")
            self.assertNotIn("gemma4:31b-cloud", entry.models)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("provider", saved)
            self.assertEqual(
                saved["providers"]["ollama"]["base_url"],
                "http://localhost:11434",
            )
            self.assertNotIn("model", saved["providers"]["ollama"])

    def test_update_catalog_keeps_order_for_existing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "providers": {
                            "groq": {
                                "base_url": "https://api.groq.com/openai/v1",
                                "models": ["model-a", "model-b", "model-c"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = LlmSettingsStore(path=path)
            store.update_catalog(provider="groq", model="model-b")
            entry = store.load().get_provider("groq")
            self.assertEqual(entry.models, ["model-a", "model-b", "model-c"])

    def test_update_catalog_appends_new_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "providers": {
                            "groq": {
                                "base_url": "https://api.groq.com/openai/v1",
                                "models": ["model-a", "model-b"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = LlmSettingsStore(path=path)
            store.update_catalog(provider="groq", model="model-c")
            entry = store.load().get_provider("groq")
            self.assertEqual(entry.models, ["model-a", "model-b", "model-c"])

    def test_update_catalog_coerces_cloud_url_for_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_settings.json"
            store = LlmSettingsStore(path=path)
            store.update_catalog(
                provider="ollama",
                base_url="https://ollama.com",
                model="gemma4:31b-cloud",
            )
            entry = store.load().get_provider("ollama")
            self.assertEqual(entry.base_url, "http://localhost:11434")
            self.assertEqual(entry.models[0], "llama3.2")


class TestEnvAuthoritativeConfig(unittest.TestCase):
    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_config_for_run_uses_env_over_legacy_json(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config(
            llm_provider="groq",
            groq_model="env-model",
        )
        catalog = MagicMock()
        catalog.base_url = "https://api.groq.com/openai/v1"
        catalog.models = ["json-model", "env-model"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        config = config_for_run()

        self.assertEqual(config.active_provider, "groq")
        self.assertEqual(config.active_model, "env-model")
        self.assertEqual(config.groq_model, "env-model")

    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_config_for_run_picks_cloud_model_when_both_ollama_vars_set(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config(
            llm_provider="ollama-cloud",
            ollama_model="llama3.2",
            ollama_base_url="http://localhost:11434",
            ollama_cloud_model="qwen3.5:cloud",
            ollama_cloud_base_url="https://ollama.com",
            ollama_cloud_api_key="cloud-key",
        )
        catalog = MagicMock()
        catalog.base_url = "https://ollama.com"
        catalog.models = ["qwen3.5:cloud"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        config = config_for_run()

        self.assertEqual(config.active_provider, "ollama-cloud")
        self.assertEqual(config.active_model, "qwen3.5:cloud")
        self.assertEqual(config.ollama_model, "qwen3.5:cloud")
        self.assertEqual(config.ollama_base_url, "https://ollama.com")
        self.assertEqual(config.ollama_api_key, "cloud-key")

    @patch("smart_automator.server.config_service.build_config_response")
    @patch("smart_automator.server.config_service.set_key")
    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    @patch("smart_automator.server.config_service.ENV_FILE")
    def test_apply_config_update_writes_cloud_vars_for_ollama_cloud(
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
        store_mock.return_value.ensure_loaded.return_value = MagicMock()

        apply_config_update(
            ConfigUpdate(
                provider="ollama-cloud",
                model="qwen3.5:cloud",
                base_url="https://ollama.com",
            )
        )

        provider_writes = [
            call.args for call in set_key_mock.call_args_list if call.args[1] == "LLM_PROVIDER"
        ]
        self.assertEqual(provider_writes, [(str(env_file_mock), "LLM_PROVIDER", "ollama-cloud")])

        model_writes = [
            call.args
            for call in set_key_mock.call_args_list
            if call.args[1] == "OLLAMA_CLOUD_MODEL"
        ]
        self.assertEqual(
            model_writes,
            [(str(env_file_mock), "OLLAMA_CLOUD_MODEL", "qwen3.5:cloud")],
        )
        base_url_writes = [
            call.args
            for call in set_key_mock.call_args_list
            if call.args[1] == "OLLAMA_CLOUD_BASE_URL"
        ]
        self.assertEqual(
            base_url_writes,
            [(str(env_file_mock), "OLLAMA_CLOUD_BASE_URL", "https://ollama.com")],
        )
        self.assertFalse(
            any(call.args[1] == "OLLAMA_MODEL" for call in set_key_mock.call_args_list)
        )

    @patch("smart_automator.server.config_service.build_config_response")
    @patch("smart_automator.server.config_service.set_key")
    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    @patch("smart_automator.server.config_service.ENV_FILE")
    def test_apply_config_update_coerces_local_ollama_to_groq(
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
        store_mock.return_value.ensure_loaded.return_value.get_provider.return_value = catalog

        apply_config_update(
            ConfigUpdate(
                provider="ollama",
                model="llama3.2",
                base_url="http://localhost:11434",
            )
        )

        provider_writes = [
            call.args for call in set_key_mock.call_args_list if call.args[1] == "LLM_PROVIDER"
        ]
        self.assertEqual(provider_writes, [(str(env_file_mock), "LLM_PROVIDER", "groq")])
        self.assertFalse(
            any(call.args[1] == "OLLAMA_MODEL" for call in set_key_mock.call_args_list)
        )


class TestOllamaEnvMigration(unittest.TestCase):
    @patch("smart_automator.server.config_service.set_key")
    @patch("smart_automator.server.config_service.ENV_FILE")
    def test_migrates_shared_cloud_vars_to_ollama_cloud(self, env_file_mock, set_key_mock):
        env_file_mock.exists.return_value = True
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "ollama-cloud",
                "OLLAMA_BASE_URL": "https://ollama.com",
                "OLLAMA_MODEL": "gemma4:31b-cloud",
                "OLLAMA_API_KEY": "legacy-key",
            },
            clear=True,
        ):
            migrate_legacy_ollama_env()

        writes = {call.args[1]: call.args[2] for call in set_key_mock.call_args_list}
        self.assertEqual(writes["OLLAMA_CLOUD_MODEL"], "gemma4:31b-cloud")
        self.assertEqual(writes["OLLAMA_CLOUD_BASE_URL"], "https://ollama.com")
        self.assertEqual(writes["OLLAMA_CLOUD_API_KEY"], "legacy-key")


class TestCreateLlm(unittest.TestCase):
    def test_ollama_cloud_ui_id_uses_ollama_client(self):
        config = Config(
            llm_provider="ollama",
            ollama_base_url="https://ollama.com",
            ollama_model="gemma4:31b-cloud",
            ollama_api_key="test-key",
        )
        llm = create_llm(config, "ollama-cloud")
        self.assertIsInstance(llm, OllamaLLM)


class TestConfigForCheck(unittest.TestCase):
    @patch("smart_automator.server.config_service.LlmSettingsStore")
    @patch("smart_automator.server.config_service.load_config")
    @patch("smart_automator.server.config_service.reload_runtime_env")
    def test_uses_form_payload_over_saved_settings(
        self,
        _reload,
        load_config_mock,
        store_mock,
    ):
        load_config_mock.return_value = Config()
        catalog = MagicMock()
        catalog.base_url = "https://api.groq.com/openai/v1"
        catalog.models = ["saved-model"]
        settings = MagicMock()
        settings.get_provider.return_value = catalog
        store_mock.return_value.ensure_loaded.return_value = settings

        update = ConfigUpdate(
            provider="ollama-cloud",
            base_url="https://ollama.com",
            model="qwen3.5:cloud",
            api_key="cloud-key",
        )
        config = config_for_check(update)

        self.assertEqual(config.llm_provider, "ollama")
        self.assertEqual(config.active_provider, "ollama-cloud")
        self.assertEqual(config.ollama_model, "qwen3.5:cloud")
        self.assertEqual(config.ollama_base_url, "https://ollama.com")
        self.assertEqual(config.ollama_api_key, "cloud-key")
        self.assertEqual(config.ollama_cloud_api_key, "cloud-key")
        self.assertTrue(is_ollama_cloud_url(config.ollama_base_url))


if __name__ == "__main__":
    unittest.main()
