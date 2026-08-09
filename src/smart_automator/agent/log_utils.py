from __future__ import annotations

import logging

_SECTION_WIDTH = 64


def log_section(logger: logging.Logger, prefix: str, title: str) -> None:
    bar = "─" * _SECTION_WIDTH
    logger.info("%s%s", prefix, bar)
    logger.info("%s%s", prefix, title)
    logger.info("%s%s", prefix, bar)
