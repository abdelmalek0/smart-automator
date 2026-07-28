import time
import threading
import unittest
from unittest.mock import MagicMock, patch

from smart_automator.agent.context import ActionResult, AgentContext, AgentOptions
from smart_automator.agent.hitl import HitlController, HumanActionRecorder, _HitlCommand
from smart_automator.agent.history import AgentStepHistory, AgentStepRecord
from smart_automator.browser.history import DOMHistoryElement
from smart_automator.reporting.builder import build_action_timeline
from smart_automator.reporting.replay_script import build_replay_steps


def _make_context(*, hitl_enabled: bool = True) -> AgentContext:
    context = AgentContext(
        task_id="test",
        browser_context=MagicMock(),
        message_manager=MagicMock(),
        options=AgentOptions(hitl_timeout_seconds=60.0),
    )
    context.hitl_enabled = hitl_enabled
    return context


def _activate_recorder(recorder: HumanActionRecorder) -> None:
    recorder._active = True


class HitlControllerTests(unittest.TestCase):
    def test_request_take_return_flow(self):
        context = _make_context()
        events: list[dict] = []
        hitl = HitlController(context, emit=events.append)

        self.assertTrue(hitl.request_intervention("Need login", source="agent"))
        self.assertTrue(context.awaiting_human)
        self.assertTrue(context.paused)
        self.assertEqual(events[-2]["type"], "human_intervention_required")
        self.assertEqual(events[-1]["type"], "status")

        with patch.object(hitl.recorder, "start", side_effect=lambda: _activate_recorder(hitl.recorder)), patch.object(
            hitl.recorder,
            "stop",
            return_value=[
                (
                    "click_element",
                    {"xpath": "html/body/button"},
                    ActionResult(
                        success=True,
                        extracted_content="Human clicked button",
                        action_name="click_element",
                    ),
                )
            ],
        ) as stop_mock, patch.object(hitl.recorder, "flush_pending_inputs") as flush_mock:
            self.assertTrue(hitl.take_control(source="manual"))
            self.assertTrue(context.human_controlling)
            self.assertTrue(hitl.return_control())

        flush_mock.assert_called_once()
        stop_mock.assert_called_once_with(finalize=False)

        self.assertFalse(context.awaiting_human)
        self.assertFalse(context.human_controlling)
        self.assertFalse(context.paused)
        self.assertEqual(len(context.history.history), 1)
        self.assertEqual(context.history.history[0].metadata.get("source"), "human")
        self.assertEqual(events[-2]["type"], "human_intervention_ended")
        context.message_manager.add_message_with_tokens.assert_not_called()
        self.assertIsNotNone(context.pending_hitl_handoff)
        self.assertEqual(context.pending_hitl_handoff.intervention_reason, "Need login")
        self.assertTrue(context.force_replan_after_hitl)

    def test_return_control_sets_force_replan_from_handoff_not_cleared_buffer(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        hitl.request_intervention("Need help", source="manual")
        with patch.object(hitl.recorder, "start", side_effect=lambda: _activate_recorder(hitl.recorder)), patch.object(
            hitl.recorder,
            "stop",
            return_value=[
                (
                    "click_element",
                    {"xpath": "html/body/button", "label": "Continue"},
                    ActionResult(
                        success=True,
                        extracted_content="Human clicked 'Continue'",
                        action_name="click_element",
                    ),
                )
            ],
        ), patch.object(hitl.recorder, "flush_pending_inputs"):
            hitl.take_control()
            hitl.return_control()

        self.assertEqual(hitl.recorder.recorded, [])
        self.assertIsNotNone(context.pending_hitl_handoff)
        self.assertTrue(context.force_replan_after_hitl)
        self.assertTrue(context.post_hitl_fresh_start)

    def test_return_control_without_recorded_actions_still_creates_handoff(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        hitl.request_intervention("Manual take control", source="manual")
        with patch.object(hitl.recorder, "start", side_effect=lambda: _activate_recorder(hitl.recorder)), patch.object(
            hitl.recorder,
            "stop",
            return_value=[],
        ), patch.object(hitl.recorder, "flush_pending_inputs"):
            hitl.take_control()
            hitl.return_control()

        self.assertIsNotNone(context.pending_hitl_handoff)
        self.assertEqual(context.pending_hitl_handoff.recorded, [])
        self.assertTrue(context.force_replan_after_hitl)

    def test_submit_take_control_sets_interrupt_flag(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        holder: dict[str, object] = {}

        def api_thread():
            ok, error = hitl.submit_command("take_control", timeout=2.0)
            holder["ok"] = ok
            holder["error"] = error

        with patch.object(hitl, "take_control", return_value=True):
            worker = threading.Thread(target=api_thread)
            worker.start()
            time.sleep(0.05)
            self.assertTrue(context.hitl_interrupt)
            hitl.process_pending_commands()
            worker.join(timeout=3.0)

        self.assertTrue(holder.get("ok"), holder.get("error"))
        self.assertFalse(context.hitl_interrupt)

    def test_submit_take_control_without_wait_returns_immediately(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)

        ok, error = hitl.submit_command("take_control", wait=False)

        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertTrue(context.hitl_interrupt)
        self.assertFalse(context.human_controlling)
        hitl.process_pending_commands()
        self.assertTrue(context.human_controlling)
        self.assertFalse(context.hitl_interrupt)

    def test_submit_take_control_emits_pending_event(self):
        context = _make_context()
        events: list[dict] = []
        hitl = HitlController(context, emit=events.append)

        hitl.submit_command("take_control", wait=False)

        self.assertEqual(events[0], {"type": "take_control_pending"})

    def test_headless_disables_intervention(self):
        context = _make_context(hitl_enabled=False)
        hitl = HitlController(context, emit=lambda _event: None)
        self.assertFalse(hitl.request_intervention("blocked"))
        self.assertFalse(context.awaiting_human)

    def test_timeout_fails_run(self):
        context = _make_context()
        events: list[dict] = []
        hitl = HitlController(context, emit=events.append)
        hitl.request_intervention("Waiting")
        context.hitl_deadline = time.time() - 1

        self.assertTrue(hitl.check_timeout())
        self.assertTrue(context.hitl_timed_out)
        self.assertTrue(context.stopped)
        self.assertEqual(events[-1]["status"], "fail")

    def test_human_actions_become_replay_steps(self):
        context = _make_context()
        history = AgentStepHistory(
            history=[
                AgentStepRecord(
                    model_output='{"action":[{"click_element":{"xpath":"html/body/button"}}]}',
                    result=[
                        ActionResult(
                            success=True,
                            extracted_content="Human clicked button",
                            action_name="click_element",
                            interacted_element=type(
                                "El",
                                (),
                                {
                                    "to_dict": lambda self: {
                                        "tagName": "button",
                                        "xpath": "html/body/button",
                                        "attributes": {"type": "submit"},
                                    }
                                },
                            )(),
                        )
                    ],
                    state=type(
                        "State",
                        (),
                        {
                            "url": "https://example.com",
                            "title": "Example",
                            "to_dict": lambda self: {
                                "url": "https://example.com",
                                "title": "Example",
                                "tabs": [],
                                "interactedElements": [],
                            },
                        },
                    )(),
                    metadata={"source": "human"},
                )
            ]
        )
        timeline = build_action_timeline(history)
        replay_steps = build_replay_steps(timeline)
        self.assertEqual(len(replay_steps), 1)
        self.assertEqual(replay_steps[0]["action"], "click_element")
        self.assertIn("xpath", replay_steps[0]["args"])

    def test_build_replay_steps_preserves_human_source(self):
        history = AgentStepHistory(
            history=[
                AgentStepRecord(
                    model_output='{"action":[{"click_element":{"xpath":"html/body/button"}}]}',
                    result=[
                        ActionResult(
                            success=True,
                            extracted_content="Human clicked button",
                            action_name="click_element",
                            interacted_element=DOMHistoryElement(
                                tag_name="flt-semantics",
                                xpath="html/body/flt-semantics",
                                highlight_index=None,
                                attributes={
                                    "role": "button",
                                    "aria-label": "Select Employee",
                                },
                                css_selector='flt-semantics[role="button"][aria-label="Select Employee"]',
                            ),
                        )
                    ],
                    state=type(
                        "State",
                        (),
                        {
                            "url": "https://example.com",
                            "title": "Example",
                            "to_dict": lambda self: {
                                "url": "https://example.com",
                                "title": "Example",
                                "tabs": [],
                                "interactedElements": [],
                            },
                        },
                    )(),
                    metadata={"source": "human"},
                )
            ]
        )
        timeline = build_action_timeline(history)
        replay_steps = build_replay_steps(timeline)
        self.assertEqual(replay_steps[0]["source"], "human")
        self.assertIn("css_selector", replay_steps[0]["args"])
        self.assertIn("Select Employee", replay_steps[0]["args"]["css_selector"])

    def test_flush_failure_preserves_recorder_buffer(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        hitl.request_intervention("Need help")
        recorded = [
            (
                "click_element",
                {"xpath": "html/body/button"},
                ActionResult(success=True, extracted_content="Human clicked button"),
            )
        ]
        with patch.object(hitl.recorder, "start", side_effect=lambda: _activate_recorder(hitl.recorder)), patch.object(
            hitl.recorder,
            "stop",
            return_value=recorded,
        ), patch.object(hitl, "_flush_to_history", side_effect=RuntimeError("flush failed")):
            hitl.take_control()
            hitl.return_control()

        self.assertEqual(len(hitl.recorder.recorded), 1)
        self.assertEqual(len(context.history.history), 0)

    def test_cancel_flushes_human_actions_to_history(self):
        from smart_automator.agent.executor import Executor

        browser_context = MagicMock()
        llm = MagicMock()
        llm.model_name = "test"
        llm.get_accumulated_usage.return_value = {}
        config = MagicMock()
        config.headless = False
        config.max_steps = 10
        config.max_actions_per_step = 5
        config.max_failures = 5
        config.max_input_tokens = 1000
        config.planning_interval = 3
        config.include_attributes = []
        config.action_delay_seconds = 0
        config.replay_action_retry_wait_seconds = 0
        config.replay_show_highlights = False
        config.max_observation_elements = 10
        config.max_observation_chars = 1000
        config.hitl_timeout_minutes = 10
        config.active_provider = "test"
        config.active_model = "test"
        config.llm_provider = "test"
        config.planner_llm_provider = ""

        executor = Executor("task", browser_context, llm, config, success_criteria="done")
        executor._context.human_controlling = True
        _activate_recorder(executor._hitl.recorder)
        recorded = [
            (
                "click_element",
                {"xpath": "html/body/button"},
                ActionResult(success=True, extracted_content="Human clicked button"),
            )
        ]
        with patch.object(
            executor._hitl.recorder,
            "flush_pending_inputs",
        ), patch.object(
            executor._hitl.recorder,
            "stop",
            return_value=recorded,
        ):
            executor.cancel()

        self.assertTrue(executor.context.stopped)
        self.assertEqual(len(executor.context.history.history), 1)
        self.assertEqual(executor.context.history.history[0].metadata["source"], "human")

    def test_human_actions_persist_to_replay_store(self):
        from smart_automator.server.replay_store import load_run_replay
        from smart_automator.server.runner import _save_run_replay_data
        from smart_automator.server.run_state import RunState

        element = type(
            "El",
            (),
            {
                "to_dict": lambda self: {
                    "tagName": "flt-semantics",
                    "xpath": "html/body/flt-semantics",
                    "attributes": {"role": "button", "aria-label": "Select Employee"},
                    "cssSelector": 'flt-semantics[role="button"][aria-label="Select Employee"]',
                }
            },
        )()
        history = AgentStepHistory(
            history=[
                AgentStepRecord(
                    model_output='{"action":[{"click_element":{"xpath":"html/body/flt-semantics","css_selector":"flt-semantics[role=\\"button\\"][aria-label=\\"Select Employee\\"]"}}]}',
                    result=[
                        ActionResult(
                            success=True,
                            extracted_content="Human clicked button",
                            action_name="click_element",
                            interacted_element=element,
                        )
                    ],
                    state=type(
                        "State",
                        (),
                        {
                            "url": "https://example.com",
                            "title": "Example",
                            "to_dict": lambda self: {
                                "url": "https://example.com",
                                "title": "Example",
                                "tabs": [],
                                "interactedElements": [],
                            },
                        },
                    )(),
                    metadata={"source": "human"},
                )
            ]
        )
        executor = MagicMock()
        executor.context.history = history
        run = RunState(
            run_id="training-run",
            task="task",
            headless=False,
            max_steps=5,
            success_criteria="Done",
        )

        with patch("smart_automator.server.runner.save_run_replay") as save_mock:
            _save_run_replay_data(run, executor)

        saved_steps = save_mock.call_args[0][1]
        self.assertEqual(saved_steps[0]["source"], "human")
        self.assertIn("css_selector", saved_steps[0]["args"])
        self.assertIn("Select Employee", saved_steps[0]["args"]["css_selector"])


def _mock_page(*, page_id: int = 0, url: str = "https://example.com"):
    playwright_page = MagicMock()
    pw_context = MagicMock()
    playwright_page.context = pw_context
    page = MagicMock()
    page.playwright_page = playwright_page
    page.page_id = page_id
    page.url.return_value = url
    return page, playwright_page, pw_context


class HumanActionRecorderTests(unittest.TestCase):
    def test_maps_click_payload_to_action_result(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        recorder._active = True
        recorder._handle_capture_event(
            {
                "eventType": "click",
                "tagName": "button",
                "xpath": "html/body/button",
                "attributes": {"type": "submit"},
            }
        )
        self.assertEqual(len(recorder.recorded), 1)
        action_name, args, result = recorder.recorded[0]
        self.assertEqual(action_name, "click_element")
        self.assertEqual(args["xpath"], "html/body/button")
        self.assertIn("css_selector", args)
        self.assertTrue(result.success)

    def test_flutter_click_payload_includes_css_selector(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        recorder._active = True
        recorder._handle_capture_event(
            {
                "eventType": "click",
                "tagName": "flt-semantics",
                "xpath": (
                    "html/body/flutter-view/flt-semantics-host/flt-semantics/"
                    "flt-semantics/flt-semantics"
                ),
                "attributes": {
                    "id": "flt-semantic-node-18",
                    "role": "button",
                    "aria-label": "Select Employee",
                },
            }
        )
        self.assertEqual(len(recorder.recorded), 1)
        action_name, args, result = recorder.recorded[0]
        self.assertEqual(action_name, "click_element")
        self.assertIn("css_selector", args)
        self.assertIn("aria-label", args["css_selector"])
        self.assertIn("Select Employee", args["css_selector"])
        self.assertIn("Select Employee", result.extracted_content)
        element = result.interacted_element
        self.assertIsNotNone(element)
        self.assertTrue(element.css_selector)

    def test_maps_input_payload_to_action_result(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        recorder._active = True
        recorder._handle_capture_event(
            {
                "eventType": "input",
                "tagName": "input",
                "xpath": "html/body/input",
                "attributes": {"type": "text"},
                "text": "hello",
            }
        )
        self.assertEqual(recorder.recorded[0][0], "input_text")
        self.assertEqual(recorder.recorded[0][1]["text"], "hello")

    def test_start_clears_recorded_buffer(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        recorder._recorded.append(
            ("click_element", {"xpath": "old"}, ActionResult(success=True))
        )
        page, _, _ = _mock_page()
        context.browser_context.get_current_page.return_value = page
        context.browser_context.get_all_tab_ids.return_value = {page.page_id}
        context.browser_context.get_page.return_value = page

        recorder.start()

        self.assertEqual(recorder.recorded, [])

    def test_start_registers_context_init_script(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        page, playwright_page, pw_context = _mock_page()
        context.browser_context.get_current_page.return_value = page
        context.browser_context.get_all_tab_ids.return_value = {page.page_id}
        context.browser_context.get_page.return_value = page

        recorder.start()

        pw_context.add_init_script.assert_called_once()
        pw_context.expose_binding.assert_called_once()
        playwright_page.evaluate.assert_called()

    def test_second_start_cycle_reuses_context_setup(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        page, playwright_page, pw_context = _mock_page()
        context.browser_context.get_current_page.return_value = page
        context.browser_context.get_all_tab_ids.return_value = {page.page_id}
        context.browser_context.get_page.return_value = page

        recorder.start()
        recorder.stop()
        recorder.start()

        pw_context.add_init_script.assert_called_once()
        pw_context.expose_binding.assert_called_once()
        self.assertGreaterEqual(playwright_page.evaluate.call_count, 2)

    def test_ensure_current_page_switches_tabs(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        page_a, playwright_page_a, pw_context_a = _mock_page(page_id=0)
        page_b, playwright_page_b, pw_context_b = _mock_page(page_id=1, url="https://example.com/tab2")
        context.browser_context.get_current_page.return_value = page_a
        context.browser_context.get_all_tab_ids.return_value = {0, 1}
        context.browser_context.get_page.side_effect = lambda page_id: page_a if page_id == 0 else page_b

        recorder.start()
        context.browser_context.get_current_page.return_value = page_b
        recorder.ensure_current_page()

        playwright_page_b.evaluate.assert_called()
        self.assertEqual(recorder._active_page_id, 1)

    def test_stop_clears_buffer_after_return(self):
        context = _make_context()
        recorder = HumanActionRecorder(context)
        recorder._active = True
        recorder._recorded.append(
            ("click_element", {"xpath": "x"}, ActionResult(success=True))
        )
        playwright_page = MagicMock()
        page = MagicMock()
        page.playwright_page = playwright_page
        context.browser_context.get_current_page.return_value = page

        returned = recorder.stop()

        self.assertEqual(len(returned), 1)
        self.assertEqual(recorder.recorded, [])


class RunnerHumanActionTests(unittest.TestCase):
    def test_human_action_does_not_capture_screenshot(self):
        from smart_automator.server.run_state import RunState
        from smart_automator.server.runner import _handle_event

        run = RunState(
            run_id="run-hitl",
            task="task",
            headless=False,
            max_steps=5,
            success_criteria="Done",
        )
        browser_context = MagicMock()

        with patch("smart_automator.server.runner._capture_screenshot") as capture_mock:
            _handle_event(
                run,
                browser_context,
                {
                    "type": "human_action",
                    "action": "click_element",
                    "args": {"xpath": "html/body/button"},
                    "result": "Human clicked button",
                },
            )
            capture_mock.assert_not_called()

        self.assertEqual(len(run.steps), 1)
        self.assertIsNone(run.steps[0].get("screenshot_url"))

    def test_human_action_indices_stay_monotonic(self):
        from smart_automator.server.run_state import RunState
        from smart_automator.server.runner import _handle_event, _next_step_index

        run = RunState(
            run_id="run-hitl",
            task="task",
            headless=False,
            max_steps=5,
            success_criteria="Done",
        )
        run.steps = [{"index": 1}, {"index": 3}]
        self.assertEqual(_next_step_index(run), 4)

        browser_context = MagicMock()
        _handle_event(
            run,
            browser_context,
            {
                "type": "human_action",
                "action": "click_element",
                "args": {"xpath": "html/body/button"},
                "result": "Human clicked button",
            },
        )
        _handle_event(
            run,
            browser_context,
            {
                "type": "human_action",
                "action": "input_text",
                "args": {"text": "hello"},
                "result": "Human entered text",
            },
        )
        self.assertEqual([step["index"] for step in run.steps], [1, 3, 4, 5])

    def test_step_end_updates_matching_index_not_list_position(self):
        from smart_automator.server.run_state import RunState
        from smart_automator.server.runner import _handle_event

        run = RunState(
            run_id="run-hitl",
            task="task",
            headless=False,
            max_steps=5,
            success_criteria="Done",
        )
        run.steps = [
            {"index": 1, "action": "agent", "status": "pass"},
            {"index": 4, "action": "click_element", "source": "human", "status": "pass"},
            {"index": 5, "action": "human_handoff", "source": "human", "status": "pass"},
        ]
        browser_context = MagicMock()
        with patch("smart_automator.server.runner._capture_screenshot", return_value=None):
            _handle_event(
                run,
                browser_context,
                {
                    "type": "step_end",
                    "step": {
                        "index": 6,
                        "action": "click_element",
                        "status": "pass",
                        "result": "clicked",
                    },
                },
            )

        self.assertEqual([step["index"] for step in run.steps], [1, 4, 5, 6])
        self.assertEqual(run.steps[1]["source"], "human")

    def test_human_steps_survive_agent_step_after_intervention(self):
        from smart_automator.server.run_state import RunState
        from smart_automator.server.runner import _handle_event

        run = RunState(
            run_id="run-hitl",
            task="task",
            headless=False,
            max_steps=5,
            success_criteria="Done",
        )
        browser_context = MagicMock()
        for index in (1, 2, 3):
            run.steps.append({"index": index, "action": "agent", "status": "pass"})

        _handle_event(
            run,
            browser_context,
            {
                "type": "human_action",
                "index": 4,
                "action": "click_element",
                "args": {"label": "Option A"},
                "result": "Human clicked 'Option A'",
            },
        )
        _handle_event(
            run,
            browser_context,
            {
                "type": "step_start",
                "step": {"index": 5, "action": "agent", "status": "running"},
            },
        )
        with patch("smart_automator.server.runner._capture_screenshot", return_value=None):
            _handle_event(
                run,
                browser_context,
                {
                    "type": "step_end",
                    "step": {
                        "index": 5,
                        "action": "click_element",
                        "status": "pass",
                        "result": "agent clicked",
                    },
                },
            )

        human_steps = [step for step in run.steps if step.get("source") == "human"]
        self.assertEqual(len(human_steps), 1)
        self.assertEqual(human_steps[0]["index"], 4)
        self.assertEqual(run.steps[-1]["index"], 5)


class UiStepIndexTests(unittest.TestCase):
    def test_alloc_ui_step_index_is_monotonic_across_human_and_agent(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        events: list[dict] = []
        hitl._emit = events.append

        with patch.object(hitl.recorder, "start", side_effect=lambda: _activate_recorder(hitl.recorder)), patch.object(
            hitl.recorder,
            "stop",
            return_value=[],
        ):
            hitl.take_control()
            hitl.recorder._handle_capture_event(
                {
                    "eventType": "click",
                    "tagName": "button",
                    "xpath": "html/body/button",
                    "label": "Continue",
                    "attributes": {},
                }
            )
            hitl.return_control()

        human_events = [event for event in events if event.get("type") == "human_action"]
        self.assertEqual(context.ui_step_index, 1)
        self.assertEqual(human_events[0]["index"], 1)

        next_index = context.alloc_ui_step_index()
        self.assertEqual(next_index, 2)
        self.assertEqual(context.ui_step_index, 2)


class MessageManagerHitlTests(unittest.TestCase):
    def test_supersede_all_plans_strips_next_steps_from_every_plan(self):
        from smart_automator.agent.messages.service import (
            MessageManager,
            PLAN_MARKER,
            VOID_SUPERSEDED_PLAN_CONTENT,
        )

        manager = MessageManager()
        manager.add_message_with_tokens({"role": "user", "content": "task"}, "init")
        manager.add_plan('{"next_steps":"go to context B"}')
        manager.add_plan('{"next_steps":"pick item in context B"}')
        manager.supersede_all_plans()
        for message in manager.get_messages():
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            self.assertNotIn("context B", content)
            if PLAN_MARKER in content:
                self.assertEqual(content, VOID_SUPERSEDED_PLAN_CONTENT)

    def test_prepare_post_hitl_resume_invalidates_navigator_output(self):
        from smart_automator.agent.messages.service import MessageManager

        manager = MessageManager()
        manager.add_plan('{"next_steps":"click login"}')
        manager.add_model_output(
            {
                "current_state": {
                    "evaluation_previous_goal": "In progress",
                    "memory": "Trying login",
                    "next_goal": "Click submit",
                },
                "action": [{"click_element": {"index": 1}}],
            }
        )
        manager.prepare_post_hitl_resume()
        last = manager.get_messages()[-1]["content"]
        self.assertIn("Interrupted", last)
        self.assertIn('"action": []', last)

    def test_prepare_post_hitl_resume_invalidates_multiple_navigator_turns(self):
        from smart_automator.agent.messages.service import MessageManager

        manager = MessageManager()
        manager.add_plan('{"next_steps":"open context B"}')
        manager.add_model_output(
            {
                "current_state": {
                    "evaluation_previous_goal": "Success",
                    "memory": "Opened context B",
                    "next_goal": "Pick item",
                },
                "action": [{"click_element": {"index": 1}}],
            }
        )
        manager.add_model_output(
            {
                "current_state": {
                    "evaluation_previous_goal": "In progress",
                    "memory": "Still in context B",
                    "next_goal": "Pick item",
                },
                "action": [{"click_element": {"index": 2}}],
            }
        )
        manager.prepare_post_hitl_resume()
        contents = [message["content"] for message in manager.get_messages()[-2:]]
        self.assertTrue(all("Interrupted" in content for content in contents))
        self.assertTrue(all("context B" not in content for content in contents))


class StepOrderingTests(unittest.TestCase):
    def test_late_human_step_inserts_by_index(self):
        """Mirror of ui/src/lib/run-steps.ts upsertStep ordering contract."""
        existing = [
            {"index": 1, "action": "agent", "status": "pass"},
            {"index": 5, "action": "agent", "status": "pass"},
            {"index": 6, "action": "agent", "status": "pass"},
        ]
        human = {"index": 4, "action": "click_element", "source": "human", "status": "pass"}
        exists = any(step["index"] == human["index"] for step in existing)
        merged = (
            [human if step["index"] == human["index"] else step for step in existing]
            if exists
            else [*existing, human]
        )
        ordered = sorted(merged, key=lambda step: step["index"])
        self.assertEqual([step["index"] for step in ordered], [1, 4, 5, 6])


class ExecutorPausePumpTests(unittest.TestCase):
    def test_pump_while_paused_uses_playwright_wait(self):
        from smart_automator.agent.executor import Executor

        browser_context = MagicMock()
        page = MagicMock()
        playwright_page = MagicMock()
        page.playwright_page = playwright_page
        browser_context.get_current_page.return_value = page

        llm = MagicMock()
        llm.model_name = "test"
        llm.get_accumulated_usage.return_value = {}
        config = MagicMock()
        config.headless = False
        config.max_steps = 10
        config.max_actions_per_step = 5
        config.max_failures = 5
        config.max_input_tokens = 1000
        config.planning_interval = 3
        config.include_attributes = []
        config.action_delay_seconds = 0
        config.replay_action_retry_wait_seconds = 0
        config.replay_show_highlights = False
        config.max_observation_elements = 10
        config.max_observation_chars = 1000
        config.hitl_timeout_minutes = 10
        config.active_provider = "test"
        config.active_model = "test"
        config.llm_provider = "test"
        config.planner_llm_provider = ""

        executor = Executor("task", browser_context, llm, config, success_criteria="done")
        executor._pump_while_paused()
        playwright_page.wait_for_timeout.assert_called_once_with(200)


class StuckEscalationTests(unittest.TestCase):
    def test_second_stuck_attempt_does_not_request_hitl(self):
        from smart_automator.agent.executor import Executor

        browser_context = MagicMock()
        llm = MagicMock()
        llm.model_name = "test"
        llm.get_accumulated_usage.return_value = {}
        config = MagicMock()
        config.headless = False
        config.max_steps = 10
        config.max_actions_per_step = 5
        config.max_failures = 5
        config.max_input_tokens = 1000
        config.planning_interval = 3
        config.include_attributes = []
        config.action_delay_seconds = 0
        config.replay_action_retry_wait_seconds = 0
        config.replay_show_highlights = False
        config.max_observation_elements = 10
        config.max_observation_chars = 1000
        config.hitl_timeout_minutes = 10
        config.active_provider = "test"
        config.active_model = "test"
        config.llm_provider = "test"
        config.planner_llm_provider = ""

        executor = Executor(
            "task",
            browser_context,
            llm,
            config,
            success_criteria="done",
        )
        executor._context.stuck_recovery_attempts = 1
        executor._context.hitl_enabled = True

        result = {
            "page_url": "https://example.com",
            "page_title": "Example",
            "action_results": [ActionResult(error="failed")],
            "auto_wait": False,
            "submit_hint_fired": False,
            "only_wait_actions": False,
            "only_done_action": False,
            "consecutive_no_action_steps": 0,
            "verification_issues": 0,
        }
        with patch.object(executor, "_run_planner", return_value={"result": {"done": False}}) as planner_mock, patch.object(
            executor,
            "_inject_stuck_recovery_hint",
        ):
            handled = executor._handle_stuck_recovery(result)

        self.assertFalse(handled)
        self.assertFalse(executor.context.awaiting_human)
        self.assertFalse(executor.context.paused)
        planner_mock.assert_called_once()


class HitlCommandQueueTests(unittest.TestCase):
    def test_commands_processed_by_executor_loop(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        result_holder: dict[str, object] = {}

        def api_thread():
            ok, error = hitl.submit_command("return_control", timeout=2.0)
            result_holder["ok"] = ok
            result_holder["error"] = error

        with patch.object(hitl, "return_control", return_value=True) as return_mock:
            worker = threading.Thread(target=api_thread)
            worker.start()
            time.sleep(0.05)
            hitl.process_pending_commands()
            worker.join(timeout=3.0)
            self.assertTrue(result_holder.get("ok"), result_holder.get("error"))
            return_mock.assert_called_once()

    def test_return_control_processed_before_page_ensure(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        context.human_controlling = True
        hitl._command_queue.put(_HitlCommand(action="return_control", kwargs={}))

        with patch.object(
            hitl.recorder,
            "ensure_current_page",
            side_effect=RuntimeError("playwright blocked"),
        ), patch.object(hitl, "return_control", return_value=True) as return_mock:
            hitl.process_pending_commands()

        return_mock.assert_called_once()

    def test_cancelled_command_is_skipped(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        command = _HitlCommand(action="return_control", kwargs={})
        command.cancelled = True
        hitl._command_queue.put(command)

        with patch.object(hitl, "return_control", return_value=True) as return_mock:
            hitl.process_pending_commands()

        return_mock.assert_not_called()
        self.assertTrue(command.done.is_set())


class HitlReturnControlTests(unittest.TestCase):
    def test_return_control_is_idempotent_when_already_clear(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        self.assertTrue(hitl.return_control())

    def test_stale_page_threshold_is_five(self):
        from smart_automator.agent.stuck_recovery import STALE_PAGE_STEP_THRESHOLD, detect_stuck_signals

        context = _make_context()
        below = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=3,
            submit_hint_fired=False,
            action_results=[],
            stale_steps_on_same_page=STALE_PAGE_STEP_THRESHOLD - 1,
        )
        at = detect_stuck_signals(
            context,
            auto_wait=False,
            consecutive_no_action_steps=0,
            num_highlights=3,
            submit_hint_fired=False,
            action_results=[],
            stale_steps_on_same_page=STALE_PAGE_STEP_THRESHOLD,
        )
        self.assertEqual(STALE_PAGE_STEP_THRESHOLD, 5)
        self.assertFalse(below.no_progress_on_same_page)
        self.assertTrue(at.no_progress_on_same_page)

    def test_submit_timeout_marks_command_cancelled(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)

        ok, error = hitl.submit_command("return_control", timeout=0.01)
        command = hitl._command_queue.get_nowait()

        self.assertFalse(ok)
        self.assertIn("timed out", error or "")
        self.assertTrue(command.cancelled)


class ExecutorHitlReplanTests(unittest.TestCase):
    def _build_executor(self):
        from smart_automator.agent.executor import Executor

        browser_context = MagicMock()
        llm = MagicMock()
        llm.model_name = "test"
        llm.get_accumulated_usage.return_value = {}
        config = MagicMock()
        config.headless = False
        config.max_steps = 10
        config.max_actions_per_step = 5
        config.max_failures = 5
        config.max_input_tokens = 1000
        config.planning_interval = 5
        config.include_attributes = []
        config.action_delay_seconds = 0
        config.replay_action_retry_wait_seconds = 0
        config.replay_show_highlights = False
        config.max_observation_elements = 10
        config.max_observation_chars = 1000
        config.hitl_timeout_minutes = 10
        config.active_provider = "test"
        config.active_model = "test"
        config.llm_provider = "test"
        config.planner_llm_provider = ""

        return Executor("task", browser_context, llm, config, success_criteria="done")

    def test_force_replan_runs_planner_before_navigation(self):
        executor = self._build_executor()
        executor._context.n_steps = 1
        executor._context.force_replan_after_hitl = True

        with patch.object(executor, "_run_planner", return_value={"result": {"done": False, "web_task": True}}) as planner_mock, patch.object(
            executor,
            "_navigate",
            return_value=None,
        ) as navigate_mock, patch.object(executor, "_should_stop", side_effect=[False, False, True]):
            executor.execute()

        planner_mock.assert_called_once()
        navigate_mock.assert_called_once()
        self.assertFalse(executor.context.force_replan_after_hitl)

    def test_pending_hitl_handoff_triggers_debrief_before_navigate(self):
        from smart_automator.agent.context import PendingHitlHandoff

        executor = self._build_executor()
        executor._context.n_steps = 2
        executor._context.pending_hitl_handoff = PendingHitlHandoff(
            recorded=[
                (
                    "click_element",
                    {"xpath": "html/body/button"},
                    ActionResult(success=True, extracted_content="Human clicked button"),
                )
            ],
            intervention_reason="Manual take control",
            intervention_source="manual",
            cycle=1,
            start_url="https://example.com",
            start_title="Home",
            end_url="https://example.com/items",
            end_title="Items",
        )

        call_order: list[str] = []

        def _debrief() -> None:
            call_order.append("debrief")
            executor._context.pending_hitl_handoff = None

        with patch.object(executor, "_run_hitl_debrief", side_effect=_debrief) as debrief_mock, patch.object(
            executor,
            "_run_planner",
            return_value={"result": {"done": False, "web_task": True}},
        ) as planner_mock, patch.object(
            executor,
            "_navigate",
            side_effect=lambda: call_order.append("navigate") or None,
        ) as navigate_mock, patch.object(executor, "_should_stop", side_effect=[False, False, True]):
            executor.execute()

        debrief_mock.assert_called_once()
        planner_mock.assert_called_once()
        navigate_mock.assert_called_once()
        self.assertEqual(call_order, ["debrief", "navigate"])

    def test_human_memory_message_includes_action_details(self):
        context = _make_context()
        hitl = HitlController(context, emit=lambda _event: None)
        recorded = [
            (
                "input_text",
                {"text": "secret", "xpath": "html/body/input"},
                ActionResult(success=True, extracted_content="Human entered text in input"),
            )
        ]
        hitl.inject_human_memory(
            recorded,
            intervention_reason="Need help",
            intervention_source="manual",
        )

        message = context.message_manager.add_message_with_tokens.call_args[0][0]
        self.assertIn("secret", message["content"])
        self.assertIn("xpath=", message["content"])


if __name__ == "__main__":
    unittest.main()
