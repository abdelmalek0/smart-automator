"""Bounded run WebSocket queue: coalesce noisy events, keep terminals."""

from __future__ import annotations

import asyncio

from smart_automator.server.run_state import enqueue_run_event


def _drain(queue: asyncio.Queue) -> list[dict]:
    items: list[dict] = []
    while True:
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items


def test_status_events_coalesce_to_latest() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    enqueue_run_event(queue, {"type": "status", "status": "running"})
    enqueue_run_event(queue, {"type": "status", "status": "awaiting_human"})
    enqueue_run_event(queue, {"type": "status", "status": "running"})
    assert _drain(queue) == [{"type": "status", "status": "running"}]


def test_same_step_updates_coalesce() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    enqueue_run_event(queue, {"type": "step_start", "step": {"index": 1, "name": "a"}})
    enqueue_run_event(queue, {"type": "step_end", "step": {"index": 1, "name": "a", "ok": True}})
    enqueue_run_event(queue, {"type": "step_start", "step": {"index": 2, "name": "b"}})
    items = _drain(queue)
    assert items == [
        {"type": "step_end", "step": {"index": 1, "name": "a", "ok": True}},
        {"type": "step_start", "step": {"index": 2, "name": "b"}},
    ]


def test_terminal_events_are_kept_when_over_capacity() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    enqueue_run_event(queue, {"type": "status", "status": "running"}, maxsize=3)
    enqueue_run_event(queue, {"type": "report_ready", "report_path": "/r"}, maxsize=3)
    enqueue_run_event(queue, {"type": "done", "status": "pass"}, maxsize=3)
    enqueue_run_event(queue, {"type": "closed"}, maxsize=3)
    enqueue_run_event(queue, {"type": "tokens_update", "tokens": 9}, maxsize=3)
    types = [item["type"] for item in _drain(queue)]
    assert "report_ready" in types
    assert "done" in types
    assert "closed" in types
    assert "status" not in types
    assert len(types) == 3


def test_error_is_not_dropped_for_status() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    enqueue_run_event(queue, {"type": "error", "message": "boom"}, maxsize=1)
    enqueue_run_event(queue, {"type": "status", "status": "running"}, maxsize=1)
    items = _drain(queue)
    assert items == [{"type": "error", "message": "boom"}]
