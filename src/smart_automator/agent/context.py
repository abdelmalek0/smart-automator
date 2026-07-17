from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..browser.dom import DEFAULT_INCLUDE_ATTRIBUTES

if TYPE_CHECKING:
    from ..browser.context import BrowserContext
    from .history import AgentStepHistory
    from .messages.service import MessageManager
    from .verification import PageSnapshot


@dataclass
class AgentOptions:
    max_steps: int = 100
    max_actions_per_step: int = 5
    max_failures: int = 5
    max_input_tokens: int = 64000
    planning_interval: int = 3
    include_attributes: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE_ATTRIBUTES))
    action_delay_seconds: float = 0.5
    replay_action_retry_wait_seconds: float = 15.0
    replay_show_highlights: bool = False
    max_observation_elements: int = 80
    max_observation_chars: int = 12000


@dataclass
class ActionResult:
    is_done: bool = False
    success: bool = False
    extracted_content: str | None = None
    error: str | None = None
    include_in_memory: bool = False
    interacted_element: object | None = None
    action_name: str | None = None
    action_index: int | None = None
    verification_status: str = "unverified"
    verification_evidence: str | None = None

    def format_memory_line(self) -> str | None:
        if self.error:
            return f"Action error: {self.error.split(chr(10))[-1]}"
        if self.extracted_content:
            from .verification import format_verification_summary

            base = self.extracted_content
            if self.verification_status != "unverified":
                return f"{base} | {format_verification_summary(self)}"
            return base
        if self.verification_status != "unverified":
            from .verification import format_verification_summary

            return format_verification_summary(self)
        return None


@dataclass
class AgentStepInfo:
    step_number: int
    max_steps: int


@dataclass
class FailedActionRecord:
    url: str
    action_name: str
    action_args: dict
    error: str


class AgentContext:
    def __init__(
        self,
        task_id: str,
        browser_context: BrowserContext,
        message_manager: MessageManager,
        options: AgentOptions | None = None,
    ):
        self.task_id = task_id
        self.browser_context = browser_context
        self.message_manager = message_manager
        self.options = options or AgentOptions()

        self.paused = False
        self.stopped = False
        self.cancel_event = threading.Event()
        self.n_steps = 0
        self.consecutive_failures = 0
        self.consecutive_no_action_steps = 0
        self.step_info: AgentStepInfo | None = None
        self.action_results: list[ActionResult] = []
        self.state_message_added = False
        self.final_answer: str | None = None
        self.last_step_metrics: dict[str, float | int] | None = None
        self.last_page_url: str | None = None
        self.last_page_title: str | None = None
        self.last_step_had_commit: bool = False
        self.last_commit_snapshot: PageSnapshot | None = None
        self.stale_steps_on_same_page = 0
        self.stuck_episode_active = False
        self.critic_runs_this_episode = 0
        self.consecutive_unvalidated_done = 0
        self.failed_actions: list[FailedActionRecord] = []
        from .history import AgentStepHistory

        self.history: AgentStepHistory = AgentStepHistory()

    def record_failed_action(self, url: str, action_name: str, action_args: dict, error: str) -> None:
        signature = {
            "url": url,
            "action_name": action_name,
            "action_args": action_args,
            "error": error,
        }
        for existing in self.failed_actions:
            if (
                existing.url == signature["url"]
                and existing.action_name == signature["action_name"]
                and existing.action_args == signature["action_args"]
                and existing.error == signature["error"]
            ):
                return
        self.failed_actions.append(
            FailedActionRecord(
                url=url,
                action_name=action_name,
                action_args=dict(action_args),
                error=error,
            )
        )
        if len(self.failed_actions) > 20:
            self.failed_actions = self.failed_actions[-20:]

    def format_failed_actions_hint(self, current_url: str) -> str:
        relevant = [record for record in self.failed_actions if record.url == current_url]
        if not relevant:
            return ""
        lines = [
            "Previously failed actions on this page (avoid repeating unless the page changed):"
        ]
        for record in relevant[-5:]:
            lines.append(
                f"- {record.action_name} {record.action_args}: {record.error}"
            )
        return "\n".join(lines)

    def check_cancelled(self):
        from ..agents.errors import RequestCancelledError

        if self.stopped or self.cancel_event.is_set():
            raise RequestCancelledError("Request cancelled")

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True
        self.cancel_event.set()
