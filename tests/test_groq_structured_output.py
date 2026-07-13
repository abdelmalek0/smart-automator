import unittest
from unittest.mock import MagicMock, patch

import httpx

from smart_automator.llm.groq import GroqLLM
from smart_automator.llm.structured_output import ensure_json_keyword_in_messages


class TestStructuredOutputHelpers(unittest.TestCase):
    def test_ensure_json_keyword_adds_hint_when_missing(self):
        messages = [{"role": "user", "content": "Do the task"}]
        prepared = ensure_json_keyword_in_messages(messages)
        combined = " ".join(str(m.get("content", "")) for m in prepared).lower()
        self.assertIn("json", combined)

    def test_ensure_json_keyword_keeps_existing_messages(self):
        messages = [{"role": "system", "content": "Return JSON only"}]
        prepared = ensure_json_keyword_in_messages(messages)
        self.assertEqual(prepared, messages)


class TestGroqJsonFallback(unittest.TestCase):
    def test_chat_json_falls_back_when_json_mode_rejected(self):
        config = MagicMock()
        config.groq_api_key = "test-key"
        config.groq_model = "llama-3.3-70b-versatile"
        llm = GroqLLM(config)
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        bad_response = httpx.Response(
            400,
            request=request,
            json={"error": {"message": "response_format not supported"}},
        )
        good_response = httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": '{"action": []}'}}]},
        )

        with patch.object(llm._client, "post", side_effect=[bad_response, good_response]) as post:
            content = llm.chat_json([{"role": "user", "content": "Return JSON"}])

        self.assertEqual(content, '{"action": []}')
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args_list[0].kwargs["json"].get("response_format"),
            {"type": "json_object"},
        )
        self.assertIsNone(post.call_args_list[1].kwargs["json"].get("response_format"))


if __name__ == "__main__":
    unittest.main()
