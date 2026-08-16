import unittest
from pathlib import Path
import tempfile

from smart_automator.agent.context import ActionResult
from smart_automator.agent.history import AgentStepHistory, AgentStepRecord, BrowserStateHistory
from smart_automator.browser.history import DOMHistoryElement
from smart_automator.reporting.builder import (
    aggregate_turn_timing,
    build_action_timeline,
    build_report_data,
    embed_step_screenshots,
    extract_run_context,
    group_timeline_by_step,
)
from smart_automator.reporting.html_report import render_html_report
from smart_automator.reporting.replay_script import (
    build_replay_steps,
    count_skipped_actions,
    format_replay_script,
)
from smart_automator.reporting import generate_run_report
from smart_automator.server.run_state import RunState


class TestReportBuilder(unittest.TestCase):
    def _sample_history(self) -> AgentStepHistory:
        element = DOMHistoryElement(
            tag_name="button",
            xpath="/html/body/button[1]",
            highlight_index=2,
            attributes={"id": "submit", "type": "submit"},
            css_selector="#submit",
        )
        model_output = (
            '{"current_state": {"next_goal": "Click submit"}, '
            '"action": [{"click_element": {"index": 2, "intent": "Submit"}}]}'
        )
        record = AgentStepRecord(
            model_output=model_output,
            result=[
                ActionResult(
                    success=True,
                    extracted_content="Clicked element 2",
                    action_name="click_element",
                    action_index=2,
                    verification_status="verified",
                    verification_evidence="DOM update",
                    interacted_element=element,
                )
            ],
            state=BrowserStateHistory(
                url="https://example.com/login",
                title="Login",
                tabs=[],
                interacted_elements=[element],
            ),
        )
        return AgentStepHistory(history=[record])

    def test_build_action_timeline_includes_xpath(self):
        timeline = build_action_timeline(self._sample_history())
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertEqual(entry["action"], "click_element")
        self.assertEqual(entry["element"]["xpath"], "/html/body/button[1]")
        self.assertEqual(entry["verification_status"], "verified")

    def test_aggregate_turn_timing_median_excludes_human_steps(self):
        steps = [
            {
                "index": 1,
                "elapsed_ms": 1000,
                "turn_timing": {"snapshot_ms": 100, "llm_navigator_ms": 400, "batch_ms": 50, "settle_ms": 10},
            },
            {
                "index": 2,
                "elapsed_ms": 3000,
                "turn_timing": {"snapshot_ms": 200, "llm_navigator_ms": 800, "batch_ms": 150, "settle_ms": 30},
            },
            {
                "index": 3,
                "elapsed_ms": 2000,
                "turn_timing": {"snapshot_ms": 150, "llm_navigator_ms": 600, "batch_ms": 100, "settle_ms": 20},
            },
            {
                "index": 4,
                "elapsed_ms": 9000,
                "source": "human",
                "turn_timing": {"snapshot_ms": 900, "llm_navigator_ms": 8000},
            },
        ]
        timing = aggregate_turn_timing(steps)
        self.assertEqual(timing["turn_ms"], 2000)
        self.assertEqual(timing["snapshot_ms"], 150)
        self.assertEqual(timing["llm_navigator_ms"], 600)
        self.assertEqual(timing["batch_ms"], 100)
        self.assertEqual(timing["settle_ms"], 20)
        self.assertEqual(timing["act_ms"], 1250)

    def test_build_report_data_uses_typical_turn_timing(self):
        run = RunState(
            run_id="test-run-id",
            task="Log in",
            headless=True,
            max_steps=10,
            success_criteria="User is logged in",
            user_id="test-user",
        )
        run.status = "pass"
        run.turn_timing = {"turn_ms": 9999, "snapshot_ms": 1, "llm_navigator_ms": 1}
        run.steps = [
            {
                "index": 1,
                "elapsed_ms": 1000,
                "turn_timing": {"snapshot_ms": 100, "llm_navigator_ms": 400},
            },
            {
                "index": 2,
                "elapsed_ms": 3000,
                "turn_timing": {"snapshot_ms": 200, "llm_navigator_ms": 800},
            },
        ]

        data = build_report_data(run, AgentStepHistory())
        self.assertEqual(data["turn_timing"]["turn_ms"], 2000)
        self.assertEqual(data["turn_timing"]["snapshot_ms"], 150)
        self.assertEqual(data["turn_timing"]["llm_navigator_ms"], 600)

    def test_render_html_report_shows_typical_turn_timing(self):
        run = RunState(run_id="abc-123", task="Test task", headless=True, max_steps=5, success_criteria="Done", user_id="test-user")
        run.status = "pass"
        run.finished_at = run.started_at + 3
        run.steps = [
            {
                "index": 1,
                "elapsed_ms": 1000,
                "turn_timing": {"snapshot_ms": 100, "llm_navigator_ms": 400},
            },
            {
                "index": 2,
                "elapsed_ms": 3000,
                "turn_timing": {"snapshot_ms": 200, "llm_navigator_ms": 800},
            },
        ]
        data = build_report_data(run, AgentStepHistory())
        html = render_html_report(data)
        self.assertIn("Typical turn timing", html)
        self.assertNotIn("Last turn timing", html)

    def test_build_report_data_includes_tokens_and_timing(self):
        run = RunState(
            run_id="test-run-id",
            task="Log in",
            headless=True,
            max_steps=10,
            success_criteria="User is logged in",
            user_id="test-user",
        )
        run.status = "pass"
        run.summary = "Logged in successfully"
        run.tokens = 1200
        run.prompt_tokens = 800
        run.completion_tokens = 400
        run.cost_usd = 0.0012
        run.finished_at = run.started_at + 12.5
        run.steps = [
            {
                "index": 1,
                "thought": "Click submit",
                "action": "click_element",
                "args": {"click_element": {"index": 2}},
                "result": "Clicked element 2",
                "status": "pass",
                "elapsed_ms": 1500,
            }
        ]

        data = build_report_data(
            run,
            self._sample_history(),
            llm_provider="groq",
            llm_model="llama-3.3-70b-versatile",
        )
        self.assertEqual(data["tokens"]["total"], 1200)
        self.assertEqual(data["tokens"]["input"], 800)
        self.assertEqual(data["tokens"]["output"], 400)
        self.assertEqual(data["status"], "pass")
        self.assertEqual(len(data["action_timeline"]), 1)
        self.assertIn("12.5s", data["duration_label"])

    def test_render_html_report_contains_sections(self):
        run = RunState(run_id="abc-123", task="Test task", headless=True, max_steps=5, success_criteria="Done", user_id="test-user")
        run.status = "pass"
        run.summary = "Done"
        run.finished_at = run.started_at + 3
        data = build_report_data(run, AgentStepHistory())
        html = render_html_report(data)
        self.assertIn("Automation Run Report", html)
        self.assertIn("Run configuration", html)
        self.assertIn("stat-card", html)
        self.assertIn("Total tokens", html)
        self.assertIn("Est. cost", html)
        self.assertIn("Test task", html)
        self.assertNotIn("DOM / XPath Action Timeline", html)

    def test_extract_website_context_from_effective_task(self):
        effective_task = (
            "Website: Deligo POS (https://posdemo.example.com/)\n\n"
            "Context: Use test credentials\n\n"
            "Task: Check categories"
        )
        context = extract_run_context(
            task="Check categories",
            effective_task=effective_task,
            website_id="site-1",
            timeline=[],
        )
        self.assertEqual(context["website_name"], "Deligo POS")
        self.assertEqual(context["website_url"], "https://posdemo.example.com/")
        self.assertEqual(context["context_prompt"], "Use test credentials")
        self.assertEqual(context["task_only"], "Check categories")

    def test_extract_detected_urls_from_task(self):
        context = extract_run_context(
            task="Go to https://example.com and log in",
            effective_task="Go to https://example.com and log in",
            website_id=None,
            timeline=[],
        )
        self.assertEqual(context["detected_urls"], ["https://example.com"])

    def test_embed_screenshots_in_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            screenshot_dir = Path(tmp)
            png_bytes = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
                b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            (screenshot_dir / "test_step_1.png").write_bytes(png_bytes)
            steps = embed_step_screenshots(
                [{"index": 1, "screenshot_url": "/screenshots/test_step_1.png"}],
                screenshot_dir,
            )
            self.assertTrue(steps[0]["screenshot_src"].startswith("data:image/png;base64,"))
            html = render_html_report({
                "run_id": "test",
                "status": "pass",
                "task": "t",
                "task_only": "t",
                "steps": steps,
                "timeline_by_step": {},
                "tokens": {},
            })
            self.assertIn("data:image/png;base64,", html)

    def test_render_html_merged_actions_in_step_details(self):
        run = RunState(run_id="abc-123", task="Test", headless=True, max_steps=5, success_criteria="Done", user_id="test-user")
        run.status = "pass"
        run.summary = "Done"
        run.finished_at = run.started_at + 1
        run.steps = [
            {
                "index": 1,
                "thought": "Click submit",
                "action": "click_element",
                "args": {},
                "result": "Clicked",
                "status": "pass",
                "elapsed_ms": 100,
            }
        ]
        data = build_report_data(run, self._sample_history())
        html = render_html_report(data)
        self.assertIn("/html/body/button[1]", html)
        self.assertIn("DOM update", html)
        self.assertIn("step-actions", html)

    def test_render_html_shows_website_url(self):
        run = RunState(
            run_id="abc-123",
            task="Check categories",
            effective_task=(
                "Website: Deligo POS (https://posdemo.example.com/)\n\n"
                "Task: Check categories"
            ),
            website_id="site-1",
            headless=True,
            max_steps=5,
            success_criteria="Categories page loads",
            user_id="test-user",
        )
        run.status = "pass"
        run.finished_at = run.started_at + 1
        data = build_report_data(run, AgentStepHistory())
        html = render_html_report(data)
        self.assertIn("Deligo POS", html)
        self.assertIn("https://posdemo.example.com/", html)

    def test_group_timeline_by_step(self):
        timeline = [
            {"step": 1, "action_num": 1, "action": "click"},
            {"step": 1, "action_num": 2, "action": "wait"},
            {"step": 2, "action_num": 1, "action": "done"},
        ]
        grouped = group_timeline_by_step(timeline)
        self.assertEqual(len(grouped[1]), 2)
        self.assertEqual(len(grouped[2]), 1)

    def test_generate_run_report_writes_file(self):
        run = RunState(run_id="file-run", task="Write report", headless=True, max_steps=5, success_criteria="Report exists", user_id="test-user")
        run.status = "pass"
        run.finished_at = run.started_at + 1
        run.steps = [
            {
                "index": 1,
                "thought": "Click submit",
                "action": "click_element",
                "args": {"click_element": {"index": 2}},
                "result": "Clicked element 2",
                "status": "pass",
                "elapsed_ms": 1500,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_run_report(
                run,
                self._sample_history(),
                output_dir=Path(tmp),
            )
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("/html/body/button[1]", content)
            self.assertIn("click_element", content)
            self.assertIn("Playwright replay", content)
            self.assertIn(".click(", content)
            self.assertIn("sync_playwright", content)

    def test_replay_steps_include_executed_actions_without_success_flag(self):
        timeline = [
            {
                "action": "click_element",
                "args": {"index": 2},
                "error": None,
                "extracted_content": "Clicked element 2",
                "element": None,
            }
        ]
        steps = build_replay_steps(timeline)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["action"], "click_element")

    def test_replay_steps_exclude_done_and_failed(self):
        timeline = [
            {
                "action": "go_to_url",
                "args": {"url": "https://example.com"},
                "success": True,
                "element": None,
            },
            {
                "action": "done",
                "args": {},
                "success": True,
                "element": None,
            },
            {
                "action": "click_element",
                "args": {"index": 1},
                "success": False,
                "error": "Element not found",
                "element": None,
            },
        ]
        steps = build_replay_steps(timeline)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["action"], "go_to_url")

    def test_replay_steps_exclude_verification_failed_mini_steps(self):
        timeline = [
            {
                "action": "click_element",
                "args": {"index": 1},
                "verification_status": "verified",
                "element": None,
            },
            {
                "action": "input_text",
                "args": {"index": 2, "text": "wrong"},
                "verification_status": "failed",
                "element": None,
            },
            {
                "action": "click_element",
                "args": {"index": 3},
                "error": "Element not found",
                "element": None,
            },
        ]
        steps = build_replay_steps(timeline)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["action"], "click_element")
        self.assertEqual(steps[0]["args"]["index"], 1)

    def test_replay_steps_keep_no_effect_mini_steps(self):
        timeline = [
            {
                "action": "go_to_url",
                "args": {"url": "https://example.com"},
                "verification_status": "verified",
                "element": None,
            },
            {
                "action": "click_element",
                "args": {"index": 2},
                "verification_status": "no_effect",
                "element": None,
            },
        ]
        steps = build_replay_steps(timeline)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["action"], "go_to_url")
        self.assertEqual(steps[1]["action"], "click_element")

    def test_replay_steps_exclude_whole_failed_step(self):
        timeline = [
            {
                "step": 1,
                "action": "input_text",
                "args": {"index": 1, "text": "bad"},
                "verification_status": "failed",
                "element": None,
            },
            {
                "step": 2,
                "action": "go_to_url",
                "args": {"url": "https://example.com"},
                "verification_status": "verified",
                "element": None,
            },
        ]
        steps = build_replay_steps(timeline)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["action"], "go_to_url")

    def test_count_skipped_actions_includes_verification_failures(self):
        timeline = [
            {
                "action": "go_to_url",
                "args": {"url": "https://example.com"},
                "verification_status": "verified",
            },
            {
                "action": "input_text",
                "args": {"text": "x"},
                "verification_status": "failed",
            },
            {
                "action": "click_element",
                "args": {"index": 1},
                "verification_status": "no_effect",
            },
            {
                "action": "click_element",
                "args": {"index": 2},
                "error": "Element not found",
            },
            {
                "action": "done",
                "args": {},
            },
        ]
        skipped_failed, skipped_done = count_skipped_actions(timeline)
        self.assertEqual(skipped_failed, 2)
        self.assertEqual(skipped_done, 1)

    def test_replay_steps_prefer_xpath_over_index(self):
        timeline = [
            {
                "action": "click_element",
                "args": {"index": 2, "intent": "Submit"},
                "element": {
                    "tagName": "button",
                    "xpath": "/html/body/button[1]",
                    "cssSelector": "#submit",
                    "highlightIndex": 2,
                },
            }
        ]
        steps = build_replay_steps(timeline)
        self.assertEqual(steps[0]["args"]["xpath"], "/html/body/button[1]")
        self.assertEqual(steps[0]["args"]["css_selector"], "#submit")
        self.assertNotIn("index", steps[0]["args"])

    def test_format_replay_script_playwright_native(self):
        steps = [
            {
                "index": 1,
                "action": "go_to_url",
                "args": {"url": "https://example.com/login"},
                "element": None,
            },
            {
                "index": 2,
                "action": "input_text",
                "args": {
                    "text": "user@example.com",
                    "xpath": "/html/body/input[1]",
                    "css_selector": "#email",
                },
                "element": {
                    "tagName": "input",
                    "attributes": {"aria-label": "Email", "id": "email"},
                },
                "element_label": "<input aria-label=\"Email\">",
            },
            {
                "index": 3,
                "action": "click_element",
                "args": {"xpath": "/html/body/button[1]", "css_selector": "#submit"},
                "element": {
                    "tagName": "button",
                    "attributes": {"id": "submit"},
                },
                "element_label": "<button#submit>",
            },
        ]
        script = format_replay_script(
            steps,
            run_id="abc-123-def",
            status="pass",
            skipped_failed=1,
            skipped_done=1,
        )
        self.assertIn('"""Playwright replay — run abc-123- (pass)."""', script)
        self.assertIn("from playwright.sync_api import sync_playwright", script)
        self.assertIn("# Excluded: 1 errored, 1 done", script)
        self.assertIn("resolve_unique", script)
        self.assertIn("click_resolved", script)
        self.assertIn("page.goto('https://example.com/login')", script)
        self.assertIn("get_by_label('Email', exact=True)", script)
        self.assertIn("fill('user@example.com')", script)
        self.assertIn("locator('#submit')", script)
        self.assertIn("click_resolved(locator)", script)
        self.assertIn('if __name__ == "__main__":', script)

    def test_format_replay_script_nth_checks_count_and_neighbors(self):
        steps = [
            {
                "index": 1,
                "action": "click_element",
                "args": {},
                "element": {
                    "tagName": "button",
                    "locatorChain": [{
                        "kind": "nth",
                        "selector": "button",
                        "index": 2,
                        "count": 3,
                        "parentTag": "div",
                        "siblingCount": 1,
                        "prevTag": "",
                        "nextTag": "",
                    }],
                },
            }
        ]
        script = format_replay_script(steps, run_id="nth-1", status="pass")
        self.assertIn("resolve_nth", script)
        self.assertIn("index=2", script)
        self.assertIn("count=3", script)
        self.assertIn("'parentTag': 'div'", script)
        self.assertNotIn(".nth(0)  # expect", script)

    def test_format_replay_script_last_uses_resolve_last(self):
        steps = [
            {
                "index": 1,
                "action": "click_element",
                "args": {},
                "element": {
                    "tagName": "button",
                    "locatorChain": [{
                        "kind": "last",
                        "selector": "button",
                        "index": 3,
                        "count": 3,
                    }],
                },
            }
        ]
        script = format_replay_script(steps, run_id="last-1", status="pass")
        self.assertIn("resolve_last(page, 'button', count=3)", script)
        self.assertNotIn("resolve_nth(page,", script)
        self.assertNotIn(".nth(2)", script)

    def test_format_replay_script_escapes_strings(self):
        steps = [
            {
                "index": 1,
                "action": "input_text",
                "args": {
                    "text": 'deligo-pos-01"',
                    "css_selector": 'input[aria-label="Email"]',
                },
                "element": {"tagName": "input", "attributes": {}},
                "element_label": "<input>",
            }
        ]
        script = format_replay_script(steps, run_id="x", status="pass")
        self.assertIn("deligo-pos-01\"", script)
        self.assertIn('input[aria-label="Email"]', script)

    def test_render_html_includes_replay_script_section(self):
        run = RunState(run_id="abc-123", task="Test", headless=True, max_steps=5, success_criteria="Done", user_id="test-user")
        run.status = "pass"
        run.finished_at = run.started_at + 1
        data = build_report_data(run, self._sample_history())
        html = render_html_report(data)
        self.assertIn("Automatic Execution", html)
        self.assertIn("Playwright replay", html)
        self.assertIn("sync_playwright", html)
        self.assertIn(".click(", html)


if __name__ == "__main__":
    unittest.main()
