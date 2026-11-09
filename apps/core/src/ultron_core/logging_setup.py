"""Structured logging (structlog) for ULTRON Core.

Both structlog loggers and standard-library loggers (uvicorn, SQLAlchemy,
Alembic) go through the same processors, so every line is either JSON
(``ULTRON_LOG_FORMAT=json``) or readable console output, with the request
id attached when there is one.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

# Keys whose values must never appear in logs.
_REDACT_KEYS = frozenset(
    {"password", "authorization", "access_token", "refresh_token", "token", "jwt_secret"}
)


def _redact_secrets(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.pop("color_message", None)  # uvicorn duplicate of "event"
    for key in list(event_dict):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "***"
    return event_dict


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_secrets,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn's own access log is replaced by our request middleware.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")
    # HTTP client libraries log full request URLs at INFO; keep them quiet so
    # provider endpoints and query strings never end up in logs.
    for name in ("httpx", "httpx2", "httpcore", "anthropic"):
        logging.getLogger(name).setLevel("WARNING")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
