"""Interruptible waits for LLM retry backoff and HITL/cancel."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock

import httpx

from smart_automator.agent.context import AgentContext
from smart_automator.agents.errors import HitlInterruptedError, RequestCancelledError
from smart_automator.llm.retry import call_with_retry, sleep_or_abort


def _http_status_error(status: int = 503) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://example.test/chat")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("retry me", request=request, response=response)


class TestSleepOrAbort(unittest.TestCase):
    def test_cancel_wakes_before_deadline(self):
        wake = threading.Event()

        def abort() -> None:
            if wake.is_set():
                raise RequestCancelledError("cancelled")

        def setter() -> None:
            time.sleep(0.05)
            wake.set()

        threading.Thread(target=setter, daemon=True).start()
        started = time.monotonic()
        with self.assertRaises(RequestCancelledError):
            sleep_or_abort(2.0, abort=abort, wake=wake)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_should_stop_returns_true(self):
        started = time.monotonic()
        stopped = sleep_or_abort(2.0, should_stop=lambda: True)
        self.assertTrue(stopped)
        self.assertLess(time.monotonic() - started, 0.2)


class TestCallWithRetryAbort(unittest.TestCase):
    def test_cancel_during_backoff_skips_later_attempts(self):
        wake = threading.Event()
        attempts = {"n": 0}

        def operation() -> str:
            attempts["n"] += 1
            raise _http_status_error()

        def cancel_check() -> None:
            if wake.is_set():
                raise RequestCancelledError("cancelled")

        def setter() -> None:
            time.sleep(0.05)
            wake.set()

        threading.Thread(target=setter, daemon=True).start()
        started = time.monotonic()
        with self.assertRaises(RequestCancelledError):
            call_with_retry(
                operation,
                max_attempts=3,
                base_delay_seconds=2.0,
                cancel_check=cancel_check,
                wake=wake,
            )
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(attempts["n"], 1)

    def test_hitl_during_backoff_skips_later_attempts(self):
        context = AgentContext("test", MagicMock(), MagicMock())
        attempts = {"n": 0}

        def operation() -> str:
            attempts["n"] += 1
            raise _http_status_error()

        def setter() -> None:
            time.sleep(0.05)
            context.hitl_interrupt = True

        threading.Thread(target=setter, daemon=True).start()
        started = time.monotonic()
        with self.assertRaises(HitlInterruptedError):
            call_with_retry(
                operation,
                max_attempts=3,
                base_delay_seconds=2.0,
                cancel_check=context.abort_wait,
                wake=context.cancel_event,
            )
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(attempts["n"], 1)


if __name__ == "__main__":
    unittest.main()
