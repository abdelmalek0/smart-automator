import unittest
from unittest.mock import MagicMock

from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions
from smart_automator.agent.stuck_recovery import (
    STALE_PAGE_STEP_THRESHOLD,
    build_stuck_recovery_hint,
    detect_stuck_signals,
    should_block_navigator_done,
    update_page_progress,
)


def _make_context() -> AgentContext:
    return AgentContext(
        task_id="test",
        browser_context=MagicMock(),
        message_manager=MagicMock(),
        options=AgentOptions(),
    )


class StuckRecoveryTests(unittest.TestCase):
    def test_submit_hint_triggers_planner_recovery(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=5,
            submit_hint_fired=True,
            action_results=[],
            stale_steps_on_same_page=1,
        )
        self.assertTrue(signals.needs_planner_recovery)
        self.assertIn("Enter/OK/Submit still visible after entry", signals.reasons)

    def test_stale_page_triggers_planner_recovery(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=3,
            submit_hint_fired=False,
            action_results=[],
            stale_steps_on_same_page=STALE_PAGE_STEP_THRESHOLD,
        )
        self.assertTrue(signals.needs_planner_recovery)
        self.assertTrue(signals.no_progress_on_same_page)

    def test_action_errors_trigger_planner_recovery(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=2,
            submit_hint_fired=False,
            action_results=[ActionResult(error="Element not found")],
            stale_steps_on_same_page=1,
        )
        self.assertTrue(signals.needs_planner_recovery)
        self.assertTrue(signals.action_errors)

    def test_auto_wait_streak_triggers_planner_recovery(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=True,
            consecutive_no_action_steps=2,
            num_highlights=4,
            submit_hint_fired=False,
            action_results=[],
            stale_steps_on_same_page=1,
        )
        self.assertTrue(signals.needs_planner_recovery)
        self.assertTrue(signals.auto_wait_with_elements)

    def test_meaningful_progress_resets_stale_counter(self):
        context = _make_context()
        context.last_page_url = "https://example.com"
        context.last_page_title = "Home"
        context.stale_steps_on_same_page = 2
        stale = update_page_progress(
            context,
            url="https://example.com/dashboard",
            title="Dashboard",
            action_errors=False,
            auto_wait=False,
            submit_hint_fired=False,
            only_wait_actions=False,
        )
        self.assertEqual(stale, 0)
        self.assertEqual(context.stale_steps_on_same_page, 0)

    def test_submit_hint_needs_action_critic(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=5,
            submit_hint_fired=True,
            action_results=[],
            stale_steps_on_same_page=1,
        )
        self.assertTrue(signals.needs_action_critic(0))
        self.assertTrue(signals.needs_action_critic(1))
        self.assertFalse(signals.needs_action_critic(3))

    def test_recovery_hint_includes_signals(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=True,
            consecutive_no_action_steps=2,
            num_highlights=3,
            submit_hint_fired=True,
            action_results=[],
            stale_steps_on_same_page=2,
        )
        hint = build_stuck_recovery_hint(signals, {"raw_preview": "broken json"})
        self.assertIn("Navigator appears stuck", hint)
        self.assertIn("broken json", hint)

    def test_only_done_action_counts_as_no_progress(self):
        context = _make_context()
        context.last_page_url = "https://example.com"
        context.last_page_title = "POS"
        stale = update_page_progress(
            context,
            url="https://example.com",
            title="POS",
            action_errors=False,
            auto_wait=False,
            submit_hint_fired=False,
            only_wait_actions=False,
            only_done_action=True,
        )
        self.assertEqual(stale, 1)

    def test_verification_failure_triggers_planner_recovery(self):
        context = _make_context()
        signals = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=3,
            submit_hint_fired=False,
            action_results=[
                ActionResult(
                    action_name="input_text",
                    action_index=1,
                    verification_status="failed",
                    verification_evidence="input still empty",
                )
            ],
            stale_steps_on_same_page=1,
        )
        self.assertTrue(signals.verification_issues)
        self.assertTrue(signals.needs_planner_recovery)

    def test_should_block_navigator_done_when_stuck(self):
        context = _make_context()
        context.stuck_episode_active = True
        self.assertTrue(should_block_navigator_done(context))
        context.stuck_episode_active = False
        context.consecutive_unvalidated_done = 1
        self.assertTrue(should_block_navigator_done(context))


if __name__ == "__main__":
    unittest.main()
