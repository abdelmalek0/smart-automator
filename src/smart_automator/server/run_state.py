from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

from .run_store import delete_run_record, list_run_records, load_run_record, save_run_record

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
        user_id: str,
        website_id: Optional[str] = None,
        effective_task: Optional[str] = None,
        cdp_url: Optional[str] = None,
        fresh_profile: bool = True,
        name: Optional[str] = None,
        source_run_id: Optional[str] = None,
        use_replay_script: bool = False,
        website_task_id: Optional[str] = None,
        run_mode: Optional[str] = None,
    ):
        self.run_id = run_id
        self.user_id = user_id
        self.task = task
        self.name = name
        self.success_criteria = success_criteria
        self.source_run_id = source_run_id
        self.use_replay_script = use_replay_script
        if run_mode:
            self.run_mode = run_mode
        elif use_replay_script:
            self.run_mode = "automatic"
        else:
            self.run_mode = "training"
        self.website_id = website_id
        self.website_task_id = website_task_id
        self.effective_task = effective_task or task
        self.headless = headless
        self.max_steps = max_steps
        self.cdp_url = cdp_url
        self.fresh_profile = fresh_profile
        self.criteria_verdict: dict[str, Any] = {}
        self.screen_excerpts: list[dict[str, Any]] = []
        self.status = "pending"
        self.hitl_reason = ""
        self.hitl_source = ""
        self.hitl_deadline: Optional[float] = None
        self.human_controlling = False
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
        self.cost_breakdown: list[dict[str, Any]] = []
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
            "user_id": self.user_id,
            "name": self.name,
            "task": self.task,
            "success_criteria": self.success_criteria,
            "source_run_id": self.source_run_id,
            "use_replay_script": self.use_replay_script,
            "run_mode": self.run_mode,
            "has_replay_script": has_replay_script,
            "website_id": self.website_id,
            "website_task_id": self.website_task_id,
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
            "cost_breakdown": self.cost_breakdown,
            "criteria_verdict": self.criteria_verdict,
            "hitl_reason": self.hitl_reason,
            "hitl_source": self.hitl_source,
            "hitl_deadline": self.hitl_deadline,
            "human_controlling": self.human_controlling,
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
            "screen_excerpts": self.screen_excerpts,
        }

    def to_persisted_dict(self, *, has_replay_script: bool = False) -> dict[str, Any]:
        data = self.to_dict(has_replay_script=has_replay_script)
        # Not part of the public API payload, but required to rehydrate after restart.
        data["effective_task"] = self.effective_task
        data["report_path"] = self.report_path
        return data

    @classmethod
    def from_persisted_dict(cls, data: dict[str, Any]) -> RunState:
        run = cls(
            run_id=str(data["run_id"]),
            user_id=str(data["user_id"]),
            task=str(data.get("task", "")),
            headless=bool(data.get("headless", False)),
            max_steps=int(data.get("max_steps", 100)),
            success_criteria=str(data.get("success_criteria", "")),
            website_id=str(data["website_id"]) if data.get("website_id") else None,
            effective_task=data.get("effective_task"),
            cdp_url=data.get("cdp_url"),
            fresh_profile=bool(data.get("fresh_profile", True)),
            name=data.get("name"),
            source_run_id=data.get("source_run_id"),
            use_replay_script=bool(data.get("use_replay_script", False)),
            website_task_id=str(data["website_task_id"]) if data.get("website_task_id") else None,
            run_mode=data.get("run_mode"),
        )
        run.criteria_verdict = dict(data.get("criteria_verdict") or {})
        run.screen_excerpts = list(
            data.get("screen_excerpts") or data.get("findings") or []
        )
        run.status = str(data.get("status", "pending"))
        run.hitl_reason = str(data.get("hitl_reason", ""))
        run.hitl_source = str(data.get("hitl_source", ""))
        run.hitl_deadline = data.get("hitl_deadline")
        run.human_controlling = bool(data.get("human_controlling", False))
        run.steps = list(data.get("steps") or [])
        run.plan = dict(data.get("plan") or {})
        run.app_context = dict(data.get("app_context") or {})
        run.extracted_steps = list(data.get("extracted_steps") or [])
        run.current_atomic_step = data.get("current_atomic_step")
        run.progress = dict(data.get("progress") or {})
        run.summary = str(data.get("summary", ""))
        run.new_tools = list(data.get("new_tools") or [])
        run.tokens = int(data.get("tokens", 0))
        run.prompt_tokens = int(data.get("prompt_tokens", 0))
        run.completion_tokens = int(data.get("completion_tokens", 0))
        run.cache_tokens = int(data.get("cache_tokens", 0))
        run.cost_usd = data.get("cost_usd")
        run.cost_breakdown = list(data.get("cost_breakdown") or [])
        run.turn_timing = dict(data.get("turn_timing") or {})
        run.started_at = float(data.get("started_at", time.time()))
        run.finished_at = data.get("finished_at")
        run.report_path = data.get("report_path")
        return run

    def persist(self, *, has_replay_script: bool = False) -> None:
        save_run_record(
            self.user_id,
            self.run_id,
            self.to_persisted_dict(has_replay_script=has_replay_script),
        )


_runs: dict[str, RunState] = {}
_MAX_RUNS_IN_MEMORY = 200
_IN_MEMORY_ACTIVE_STATUSES = ("pending", "running", "awaiting_human")
_start_locks_guard = threading.Lock()
_user_start_locks: dict[str, threading.Lock] = {}


def user_run_start_lock(user_id: str) -> threading.Lock:
    with _start_locks_guard:
        lock = _user_start_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_start_locks[user_id] = lock
        return lock


def has_in_memory_active_run(user_id: str) -> bool:
    return any(
        run.user_id == user_id and run.status in _IN_MEMORY_ACTIVE_STATUSES
        for run in _runs.values()
    )


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
        (run for run in _runs.values() if run.status not in ("pending", "running", "awaiting_human")),
        key=lambda run: run.finished_at or 0,
    )
    to_remove = len(_runs) - _MAX_RUNS_IN_MEMORY
    for run in finished[:to_remove]:
        _runs.pop(run.run_id, None)


def remove_run(run_id: str) -> RunState | None:
    return _runs.pop(run_id, None)


def get_run_for_user(user_id: str, run_id: str) -> RunState | None:
    run = get_run(run_id)
    if run is not None:
        if run.user_id != user_id:
            return None
        return run
    record = load_run_record(user_id, run_id)
    if record is None:
        return None
    run = RunState.from_persisted_dict(record)
    add_run(run)
    return run


def list_runs_for_user(user_id: str) -> list[RunState]:
    in_memory = [run for run in _runs.values() if run.user_id == user_id]
    memory_ids = {run.run_id for run in in_memory}
    for record in list_run_records(user_id):
        run_id = str(record.get("run_id", ""))
        if not run_id or run_id in memory_ids:
            continue
        run = RunState.from_persisted_dict(record)
        add_run(run)
        in_memory.append(run)
    in_memory.sort(key=lambda run: run.started_at, reverse=True)
    return in_memory


def delete_run_for_user(user_id: str, run_id: str) -> None:
    remove_run(run_id)
    delete_run_record(user_id, run_id)
