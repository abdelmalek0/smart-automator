import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from smart_automator.config import Config
from smart_automator.llm.ollama import OllamaLLM
from smart_automator.main import create_llm
from smart_automator.server.config_service import config_for_check
from smart_automator.server.models import ConfigUpdate
from smart_automator.server.provider_utils import (
    coerce_provider_base_url,
    coerce_provider_model,
    format_llm_connection_error,
    is_ollama_cloud_url,
)
from smart_automator.storage.llm_settings import LlmSettingsStore


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
        self.assertIn("OLLAMA_API_KEY", message)


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
            self.assertEqual(entry.model, "llama3.2")
            self.assertNotIn("gemma4:31b-cloud", entry.models)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["providers"]["ollama"]["base_url"],
                "http://localhost:11434",
            )

    def test_update_active_coerces_cloud_url_for_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_settings.json"
            store = LlmSettingsStore(path=path)
            store.update_active(
                provider="ollama",
                base_url="https://ollama.com",
                model="gemma4:31b-cloud",
            )
            entry = store.load().get_provider("ollama")
            self.assertEqual(entry.base_url, "http://localhost:11434")
            self.assertEqual(entry.model, "llama3.2")


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
        active = MagicMock()
        active.base_url = "https://api.groq.com/openai/v1"
        active.model = "saved-model"
        settings = MagicMock()
        settings.provider = "groq"
        settings.get_provider.return_value = active
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
        self.assertTrue(is_ollama_cloud_url(config.ollama_base_url))


if __name__ == "__main__":
    unittest.main()
