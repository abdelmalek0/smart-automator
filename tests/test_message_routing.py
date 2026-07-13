import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.messages.service import MessageManager
from smart_automator.agents.action_critic import ACTION_CRITIC_SYSTEM_PROMPT, ActionCriticAgent
from smart_automator.agents.base import BaseAgent
from smart_automator.agents.planner import PlannerAgent
from smart_automator.llm.base import BaseLLM


class _RecordingLLM(BaseLLM):
    def __init__(self):
        self.last_messages: list[dict] | None = None

    @property
    def model_name(self) -> str:
        return "test-model"

    @property
    def supports_structured_output(self) -> bool:
        return False

    def chat(self, messages, temperature=0.7) -> str:
        self.last_messages = messages
        system = messages[0].get("content", "") if messages else ""
        if "action critic" in system.lower():
            return '{"action": [{"click_element": {"index": 2, "intent": "Submit"}}]}'
        return '{"observation": "", "done": false, "challenges": "", "next_steps": "go", "final_answer": "", "reasoning": "", "web_task": true}'

    def chat_json(self, messages, temperature=0.7) -> str:
        return self.chat(messages, temperature)


class TestInvokeMessageRouting(unittest.TestCase):
    def test_invoke_preserves_custom_messages_when_message_manager_exists(self):
        llm = _RecordingLLM()
        manager = MessageManager()
        manager.init_task_messages("navigator system prompt", "task")
        agent = BaseAgent(llm, "unused", message_manager=manager)

        custom = [
            {"role": "system", "content": "planner-only prompt"},
            {"role": "user", "content": "compact state"},
        ]
        agent.invoke(custom, temperature=0.2)

        self.assertEqual(llm.last_messages[0]["content"], "planner-only prompt")
        self.assertEqual(llm.last_messages[1]["content"], "compact state")

    def test_planner_execute_uses_planner_system_prompt(self):
        llm = _RecordingLLM()
        manager = MessageManager()
        manager.init_task_messages("navigator system prompt", "task")
        manager.add_message_with_tokens({"role": "user", "content": "page state"})

        planner = PlannerAgent(llm, MagicMock(), manager)
        output = planner.execute()

        self.assertEqual(llm.last_messages[0]["content"], planner._system_prompt)
        self.assertIn("result", output)

    def test_action_critic_uses_compact_messages(self):
        llm = _RecordingLLM()
        manager = MessageManager()
        manager.init_task_messages("navigator system prompt", "task")
        critic = ActionCriticAgent(llm, manager)
        suggestion = critic.suggest_actions("submit still visible")

        self.assertIsNotNone(suggestion)
        self.assertEqual(llm.last_messages[0]["content"], ACTION_CRITIC_SYSTEM_PROMPT)
        self.assertEqual(len(llm.last_messages), 2)
        self.assertIn("Stuck reason", llm.last_messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
