from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from loguru import logger

from .server.paths import PROJECT_ROOT

_configured = False

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}"
)
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)
_STD_LIB_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "uvicorn.asgi",
    "fastapi",
    "starlette",
    "websockets",
    "httpx",
)


class InterceptHandler(logging.Handler):
    """Route stdlib logging records through Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        opt_kwargs: dict = {}
        if record.exc_info:
            opt_kwargs["exception"] = record.exc_info

        logger.patch(
            lambda r: r.update(
                name=record.name,
                function=record.funcName,
                line=record.lineno,
                file=record.pathname,
            )
        ).opt(**opt_kwargs).log(level, record.getMessage())


def _log_dir() -> Path:
    explicit = os.getenv("LOG_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return PROJECT_ROOT / "data" / "logs"


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    debug = level == "DEBUG"
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stderr,
        level=level,
        format=_CONSOLE_FORMAT,
        colorize=True,
        backtrace=False,
        diagnose=False,
    )

    file_sink_kwargs = {
        "level": level,
        "format": _FILE_FORMAT,
        "rotation": "10 MB",
        "retention": "14 days",
        "compression": "zip",
        "encoding": "utf-8",
        "enqueue": True,
        "backtrace": True,
        "diagnose": False,
    }

    logger.add(log_dir / "backend.log", **file_sink_kwargs)
    logger.add(
        log_dir / "backend-error.log",
        **{**file_sink_kwargs, "level": "ERROR"},
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    for name in _STD_LIB_LOGGERS:
        lib_logger = logging.getLogger(name)
        lib_logger.handlers = []
        lib_logger.propagate = True
        if name in ("uvicorn.access", "websockets", "httpx"):
            # Access/HTTP client lines are emitted at INFO; keep them for LOG_LEVEL=DEBUG only.
            lib_logger.setLevel(logging.DEBUG if debug else logging.WARNING)
        elif name.startswith("uvicorn"):
            lib_logger.setLevel(logging.DEBUG if debug else logging.WARNING)
        else:
            lib_logger.setLevel(level)

    _configured = True
    logger.info("Logging configured (level={}, dir={})", level, log_dir)


async def shutdown_logging() -> None:
    await logger.complete()
