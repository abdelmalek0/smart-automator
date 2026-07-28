from __future__ import annotations

import httpx

from ..server.provider_utils import format_llm_connection_error


class ChatModelAuthError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class ChatModelForbiddenError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class ChatModelBadRequestError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class RequestCancelledError(Exception):
    pass


class HitlInterruptedError(Exception):
    """Raised when HITL take-control interrupts an in-flight agent turn."""


class MaxStepsReachedError(Exception):
    pass


class MaxFailuresReachedError(Exception):
    pass


class ResponseParseError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


def is_authentication_error(error: Exception) -> bool:
    message = str(error).lower()
    if isinstance(error, ChatModelAuthError):
        return True
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 401:
        return True
    return "authentication" in message or " 401" in message or "api key" in message


def is_forbidden_error(error: Exception) -> bool:
    if isinstance(error, ChatModelForbiddenError):
        return True
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 403:
        return True
    message = str(error)
    return " 403" in message and "forbidden" in message.lower()


def is_bad_request_error(error: Exception) -> bool:
    if isinstance(error, ChatModelBadRequestError):
        return True
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 400:
        return True
    message = str(error).lower()
    return " 400" in message or "badrequest" in message or "invalid parameter" in message


def is_aborted_error(error: Exception) -> bool:
    if isinstance(error, RequestCancelledError):
        return True
    return error.__class__.__name__ == "AbortError" or "aborted" in str(error).lower()


def classify_llm_error(error: Exception) -> Exception:
    if is_authentication_error(error):
        return ChatModelAuthError(str(error), error)
    if is_forbidden_error(error):
        return ChatModelForbiddenError(format_llm_connection_error(error), error)
    if is_bad_request_error(error):
        return ChatModelBadRequestError(str(error), error)
    if is_aborted_error(error):
        return RequestCancelledError(str(error))
    return error
