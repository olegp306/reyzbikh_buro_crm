"""Structured logging setup via structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from crm.config import AppEnv, Settings

SECRET_KEY_FRAGMENTS: tuple[str, ...] = (
    "token",
    "key",
    "secret",
    "password",
    "authorization",
)


def mask_secrets(
    _logger: Any,
    _name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor that replaces secret-looking values with '***'."""
    for key in list(event_dict.keys()):
        lowered = key.lower()
        if any(frag in lowered for frag in SECRET_KEY_FRAGMENTS):
            event_dict[key] = "***"
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog and stdlib logging according to settings."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        mask_secrets,
    ]

    if settings.app_env is AppEnv.prod:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
