import unittest
from unittest.mock import MagicMock, patch

import httpx

from smart_automator.agent.history import AgentStepHistory
from smart_automator.agent.executor import Executor
from smart_automator.llm.base import BaseLLM
from smart_automator.llm.ollama import OllamaLLM
from smart_automator.reporting.builder import build_report_data
from smart_automator.server.runner import _handle_event
from smart_automator.server.run_state import RunState


class _UsageLLM(BaseLLM):
    def __init__(self, model_name: str = "test-model"):
        super().__init__()
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def chat(self, messages, temperature=0.7) -> str:
        return ""

    def add_usage(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_tokens: int = 0,
    ) -> None:
        self._record_usage(
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_tokens": cache_tokens,
            }
        )


class TestBaseLLMUsage(unittest.TestCase):
    def test_accumulates_usage_across_multiple_calls(self):
        llm = _UsageLLM()
        llm.add_usage(prompt_tokens=100, completion_tokens=20)
        llm.add_usage(prompt_tokens=50, completion_tokens=10, cache_tokens=5)
        usage = llm.get_accumulated_usage()
        self.assertEqual(usage["prompt_tokens"], 150)
        self.assertEqual(usage["completion_tokens"], 30)
        self.assertEqual(usage["cache_tokens"], 5)


class TestOllamaUsage(unittest.TestCase):
    def test_records_prompt_and_completion_tokens_from_response(self):
        config = MagicMock()
        config.ollama_base_url = "http://localhost:11434"
        config.ollama_model = "llama3.2"
        config.ollama_api_key = ""
        llm = OllamaLLM(config)
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(
            200,
            request=request,
            json={
                "message": {"content": "hello"},
                "prompt_eval_count": 120,
                "eval_count": 35,
            },
        )

        with patch.object(llm._client, "post", return_value=response):
            content = llm.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(content, "hello")
        usage = llm.get_accumulated_usage()
        self.assertEqual(usage["prompt_tokens"], 120)
        self.assertEqual(usage["completion_tokens"], 35)
        self.assertEqual(usage["cache_tokens"], 0)

    def test_accumulates_usage_across_multiple_ollama_calls(self):
        config = MagicMock()
        config.ollama_base_url = "http://localhost:11434"
        config.ollama_model = "llama3.2"
        config.ollama_api_key = ""
        llm = OllamaLLM(config)
        request = httpx.Request("POST", "http://localhost:11434/api/chat")

        def make_response(prompt_tokens: int, completion_tokens: int) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={
                    "message": {"content": "ok"},
                    "prompt_eval_count": prompt_tokens,
                    "eval_count": completion_tokens,
                },
            )

        with patch.object(
            llm._client,
            "post",
            side_effect=[make_response(80, 10), make_response(40, 5)],
        ):
            llm.chat([{"role": "user", "content": "first"}])
            llm.chat([{"role": "user", "content": "second"}])

        usage = llm.get_accumulated_usage()
        self.assertEqual(usage["prompt_tokens"], 120)
        self.assertEqual(usage["completion_tokens"], 15)


class TestExecutorTokenEmission(unittest.TestCase):
    def _make_executor(
        self,
        llm: BaseLLM,
        *,
        planner_llm: BaseLLM | None = None,
        planner_provider: str = "",
        planner_model: str | None = None,
    ) -> tuple[Executor, list[dict]]:
        events: list[dict] = []
        browser_context = MagicMock()
        config = MagicMock()
        config.max_input_tokens = 128000
        config.max_steps = 5
        config.max_actions_per_step = 5
        config.max_failures = 3
        config.planning_interval = 1
        config.include_attributes = []
        config.action_delay_seconds = 0
        config.max_observation_elements = 80
        config.max_observation_chars = 12000
        config.active_provider = "groq"
        config.llm_provider = "groq"
        config.active_model = llm.model_name
        config.planner_llm_provider = planner_provider
        if planner_model is not None:
            config.planner_model = planner_model
        executor = Executor(
            "task",
            browser_context,
            llm,
            config,
            planner_llm=planner_llm,
            on_event=events.append,
        )
        return executor, events

    def test_shared_llm_is_not_double_counted(self):
        llm = _UsageLLM("shared-model")
        llm.add_usage(prompt_tokens=100, completion_tokens=50)
        executor, events = self._make_executor(llm)

        executor.flush_token_usage()

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["type"], "tokens_update")
        self.assertEqual(event["prompt_tokens"], 100)
        self.assertEqual(event["completion_tokens"], 50)
        self.assertEqual(event["tokens"], 150)

    def test_separate_llms_sum_cumulative_usage(self):
        navigator = _UsageLLM("nav-model")
        planner = _UsageLLM("plan-model")
        navigator.add_usage(prompt_tokens=100, completion_tokens=40)
        planner.add_usage(prompt_tokens=200, completion_tokens=60)
        executor, events = self._make_executor(
            navigator,
            planner_llm=planner,
            planner_provider="google",
            planner_model="plan-model",
        )

        executor.flush_token_usage()

        event = events[0]
        self.assertEqual(event["prompt_tokens"], 300)
        self.assertEqual(event["completion_tokens"], 100)
        self.assertEqual(event["tokens"], 400)

    @patch("smart_automator.agent.executor.compute_cost_usd")
    def test_cost_is_computed_per_llm_instance(self, compute_cost):
        navigator = _UsageLLM("nav-model")
        planner = _UsageLLM("plan-model")
        navigator.add_usage(prompt_tokens=100, completion_tokens=10)
        planner.add_usage(prompt_tokens=50, completion_tokens=5)
        compute_cost.side_effect = [0.01, 0.02]
        executor, events = self._make_executor(
            navigator,
            planner_llm=planner,
            planner_provider="google",
            planner_model="plan-model",
        )

        executor.flush_token_usage()

        self.assertEqual(compute_cost.call_count, 2)
        compute_cost.assert_any_call(
            "groq",
            "nav-model",
            prompt_tokens=100,
            completion_tokens=10,
            cache_tokens=0,
        )
        compute_cost.assert_any_call(
            "google",
            "plan-model",
            prompt_tokens=50,
            completion_tokens=5,
            cache_tokens=0,
        )
        self.assertEqual(events[0]["cost_usd"], 0.03)

    def test_action_critic_emits_updated_totals(self):
        llm = _UsageLLM("nav-model")
        llm.add_usage(prompt_tokens=100, completion_tokens=20)
        executor, events = self._make_executor(llm)

        with patch.object(
            executor._action_critic,
            "suggest_actions",
            return_value={"actions": [{"click_element": {"index": 1}}], "raw_preview": "click"},
        ):
            executor._run_action_critic(MagicMock(reasons=["stuck"]))

        token_events = [event for event in events if event["type"] == "tokens_update"]
        self.assertEqual(len(token_events), 1)
        self.assertEqual(token_events[0]["tokens"], 120)


class TestRunnerTokenHandling(unittest.TestCase):
    def test_tokens_update_replaces_run_state_with_cumulative_snapshot(self):
        run = RunState(run_id="run-1", task="task", headless=True, max_steps=5)
        browser_context = MagicMock()

        _handle_event(
            run,
            browser_context,
            {
                "type": "tokens_update",
                "tokens": 150,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cache_tokens": 0,
                "cost_usd": 0.001,
            },
        )
        _handle_event(
            run,
            browser_context,
            {
                "type": "tokens_update",
                "tokens": 400,
                "prompt_tokens": 300,
                "completion_tokens": 100,
                "cache_tokens": 5,
                "cost_usd": 0.004,
            },
        )

        self.assertEqual(run.tokens, 400)
        self.assertEqual(run.prompt_tokens, 300)
        self.assertEqual(run.completion_tokens, 100)
        self.assertEqual(run.cache_tokens, 5)
        self.assertEqual(run.cost_usd, 0.004)

    def test_report_data_uses_final_run_token_snapshot(self):
        run = RunState(run_id="run-1", task="task", headless=True, max_steps=5)
        run.status = "pass"
        run.tokens = 400
        run.prompt_tokens = 300
        run.completion_tokens = 100
        run.cost_usd = 0.004
        run.finished_at = run.started_at + 5

        data = build_report_data(run, AgentStepHistory())
        self.assertEqual(data["tokens"]["total"], 400)
        self.assertEqual(data["tokens"]["input"], 300)
        self.assertEqual(data["tokens"]["output"], 100)


if __name__ == "__main__":
    unittest.main()
