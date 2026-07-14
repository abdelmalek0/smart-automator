import unittest
from pathlib import Path
import tempfile

from smart_automator.agent.context import ActionResult
from smart_automator.agent.history import AgentStepHistory, AgentStepRecord, BrowserStateHistory
from smart_automator.browser.history import DOMHistoryElement
from smart_automator.reporting.builder import build_action_timeline, build_report_data
from smart_automator.reporting.html_report import render_html_report
from smart_automator.reporting.replay_script import build_replay_steps, format_replay_script
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

    def test_build_report_data_includes_tokens_and_timing(self):
        run = RunState(
            run_id="test-run-id",
            task="Log in",
            headless=True,
            max_steps=10,
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
        self.assertEqual(data["status"], "pass")
        self.assertEqual(len(data["action_timeline"]), 1)
        self.assertIn("12.5s", data["duration_label"])

    def test_render_html_report_contains_sections(self):
        run = RunState(run_id="abc-123", task="Test task", headless=True, max_steps=5)
        run.status = "pass"
        run.summary = "Done"
        run.finished_at = run.started_at + 3
        data = build_report_data(run, AgentStepHistory())
        html = render_html_report(data)
        self.assertIn("Automation Run Report", html)
        self.assertIn("DOM / XPath Action Timeline", html)
        self.assertIn("Total tokens", html)
        self.assertIn("Test task", html)

    def test_generate_run_report_writes_file(self):
        run = RunState(run_id="file-run", task="Write report", headless=True, max_steps=5)
        run.status = "pass"
        run.finished_at = run.started_at + 1
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
            self.assertIn(".click()", content)
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
        self.assertIn("page.goto('https://example.com/login')", script)
        self.assertIn("page.get_by_label('Email').fill('user@example.com')", script)
        self.assertIn("page.locator('#submit').click()", script)
        self.assertIn('if __name__ == "__main__":', script)

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
        run = RunState(run_id="abc-123", task="Test", headless=True, max_steps=5)
        run.status = "pass"
        run.finished_at = run.started_at + 1
        data = build_report_data(run, self._sample_history())
        html = render_html_report(data)
        self.assertIn("Playwright replay", html)
        self.assertIn("sync_playwright", html)
        self.assertIn(".click()", html)


if __name__ == "__main__":
    unittest.main()
