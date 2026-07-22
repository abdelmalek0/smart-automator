from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..agent.executor import Executor


class RunState:
    """In-memory state for a single automation run."""

    def __init__(
        self,
        run_id: str,
        task: str,
        headless: bool,
        max_steps: int,
        success_criteria: str,
        website_id: Optional[str] = None,
        effective_task: Optional[str] = None,
        cdp_url: Optional[str] = None,
        fresh_profile: bool = False,
        name: Optional[str] = None,
        source_run_id: Optional[str] = None,
        use_replay_script: bool = False,
    ):
        self.run_id = run_id
        self.task = task
        self.name = name
        self.success_criteria = success_criteria
        self.source_run_id = source_run_id
        self.use_replay_script = use_replay_script
        self.website_id = website_id
        self.effective_task = effective_task or task
        self.headless = headless
        self.max_steps = max_steps
        self.cdp_url = cdp_url
        self.fresh_profile = fresh_profile
        self.criteria_verdict: dict[str, Any] = {}
        self.status = "pending"
        self.steps: list[dict[str, Any]] = []
        self.plan: dict[str, Any] = {}
        self.app_context: dict[str, Any] = {}
        self.extracted_steps: list[dict[str, Any]] = []
        self.current_atomic_step: Optional[int] = None
        self.progress: dict[str, Any] = {}
        self.summary = ""
        self.new_tools: list[str] = []
        self.tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cache_tokens = 0
        self.cost_usd: Optional[float] = None
        self.turn_timing: dict[str, Any] = {}
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.report_path: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: list[asyncio.Queue] = []
        self._cancelled = threading.Event()
        self.executor: Optional[Executor] = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def broadcast(self, event: dict[str, Any]) -> None:
        if self._loop and not self._loop.is_closed():
            for queue in list(self._subscribers):
                self._loop.call_soon_threadsafe(queue.put_nowait, event)

    def to_summary(self, *, has_replay_script: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "task": self.task,
            "success_criteria": self.success_criteria,
            "source_run_id": self.source_run_id,
            "use_replay_script": self.use_replay_script,
            "has_replay_script": has_replay_script,
            "website_id": self.website_id,
            "headless": self.headless,
            "max_steps": self.max_steps,
            "cdp_url": self.cdp_url,
            "fresh_profile": self.fresh_profile,
            "status": self.status,
            "step_count": len(self.steps),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "tokens": self.tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cache_tokens": self.cache_tokens,
            "cost_usd": self.cost_usd,
            "criteria_verdict": self.criteria_verdict,
        }

    def to_dict(self, *, has_replay_script: bool = False) -> dict[str, Any]:
        return {
            **self.to_summary(has_replay_script=has_replay_script),
            "steps": self.steps,
            "plan": self.plan,
            "app_context": self.app_context,
            "extracted_steps": self.extracted_steps,
            "current_atomic_step": self.current_atomic_step,
            "progress": self.progress,
            "new_tools": self.new_tools,
            "turn_timing": self.turn_timing,
        }


_runs: dict[str, RunState] = {}
_MAX_RUNS_IN_MEMORY = 200


def get_run(run_id: str) -> RunState | None:
    return _runs.get(run_id)


def list_runs() -> list[RunState]:
    return list(_runs.values())


def add_run(run: RunState) -> None:
    _runs[run.run_id] = run
    _evict_old_runs()


def _evict_old_runs() -> None:
    if len(_runs) <= _MAX_RUNS_IN_MEMORY:
        return
    finished = sorted(
        (run for run in _runs.values() if run.status not in ("pending", "running")),
        key=lambda run: run.finished_at or 0,
    )
    to_remove = len(_runs) - _MAX_RUNS_IN_MEMORY
    for run in finished[:to_remove]:
        _runs.pop(run.run_id, None)
