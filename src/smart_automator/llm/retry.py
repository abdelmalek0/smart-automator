from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_SECONDS = 1.0


def sleep_or_abort(
    seconds: float,
    *,
    abort: Callable[[], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    wake: threading.Event | None = None,
    slice_seconds: float = 0.1,
) -> bool:
    """Sleep up to ``seconds``.

    ``abort()`` may raise (cancel / HITL). ``should_stop()`` ends the wait
    without raising. ``wake`` unblocks immediately when set (Cancel).
    Returns True if ``should_stop`` fired.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    slice_seconds = max(0.0, slice_seconds)
    while True:
        if abort is not None:
            abort()
        if should_stop is not None and should_stop():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        chunk = min(slice_seconds, remaining) if slice_seconds else remaining
        if chunk <= 0:
            return False
        if wake is not None:
            wake.wait(timeout=chunk)
        else:
            time.sleep(chunk)


def _is_retryable_http_error(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(
        error,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        ),
    )


def call_with_retry(
    operation: Callable[[], T],
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = _DEFAULT_BASE_DELAY_SECONDS,
    cancel_check: Callable[[], None] | None = None,
    wake: threading.Event | None = None,
) -> T:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        if cancel_check:
            cancel_check()
        try:
            return operation()
        except Exception as error:
            last_error = error
            if attempt + 1 >= max_attempts or not _is_retryable_http_error(error):
                raise
            delay = base_delay_seconds * (2**attempt)
            status_code = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else None
            )
            log.warning(
                "LLM request retry attempt=%d/%d status=%s delay_s=%.1f error=%s",
                attempt + 2,
                max_attempts,
                status_code if status_code is not None else "n/a",
                delay,
                error,
            )
            sleep_or_abort(delay, abort=cancel_check, wake=wake)
    if last_error is not None:
        raise last_error
    raise RuntimeError("call_with_retry exhausted without result")
