from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_SECONDS = 1.0


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
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("call_with_retry exhausted without result")
