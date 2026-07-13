import unittest

from smart_automator.agent.messages.service import (
    CURRENT_STATE_MARKER,
    HISTORY_START_MARKER,
    MessageManager,
    MessageManagerSettings,
)


class TestMessageManagerCutMessages(unittest.TestCase):
    def _build_manager(self, *, max_tokens: int = 120) -> MessageManager:
        manager = MessageManager(MessageManagerSettings(max_input_tokens=max_tokens))
        manager.init_task_messages("system", "do the task")
        for step in range(6):
            manager.add_model_output(
                {
                    "current_state": {"memory": f"step {step}", "next_goal": "continue"},
                    "action": [{"wait": {"seconds": 1}}],
                }
            )
            manager.add_message_with_tokens(
                {"role": "user", "content": f"Action result {step}: ok"},
            )
        manager.add_state_message(
            f"{CURRENT_STATE_MARKER}\n" + ("x" * 4000)
        )
        return manager

    def test_drops_oldest_history_and_adds_summary(self):
        manager = self._build_manager(max_tokens=500)
        before_count = len(manager.history.messages)
        manager.cut_messages()
        summary_messages = [
            stored.message["content"]
            for stored in manager.history.messages
            if isinstance(stored.message.get("content"), str)
            and "[Earlier history summarized]" in stored.message["content"]
        ]
        self.assertTrue(summary_messages)
        self.assertLess(len(manager.history.messages), before_count)
        self.assertLessEqual(manager.history.total_tokens, manager.settings.max_input_tokens)

    def test_preserves_protected_prefix(self):
        manager = self._build_manager(max_tokens=500)
        manager.cut_messages()
        protected = "\n".join(
            str(stored.message.get("content", ""))
            for stored in manager.history.messages[:5]
        )
        self.assertIn(HISTORY_START_MARKER, protected)
        self.assertIn("do the task", protected)


if __name__ == "__main__":
    unittest.main()
