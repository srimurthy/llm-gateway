"""Structured logging. Prompts and completions are never logged; only metadata is."""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog
from structlog.typing import Processor

_NOISY_LOGGERS = ("botocore", "aiobotocore", "httpx", "httpcore", "openai", "uvicorn.access")


def configure_logging(level: str, fmt: Literal["json", "console"]) -> None:
    numeric_level = logging.getLevelNamesMapping()[level]
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer: Processor
    if fmt == "json":
        shared.append(structlog.processors.dict_tracebacks)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, botocore) through the same renderer.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, numeric_level))
