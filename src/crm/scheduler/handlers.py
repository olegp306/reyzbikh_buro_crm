"""Job-type → handler registry.

Handlers are plain async functions ``(container, job) -> None``. They run
inside the worker's per-job try/except: a raised exception triggers
reschedule (with backoff) or terminal failure.

A handler is free to open its OWN UoW for the real domain work — it
should NOT rely on the worker's job-control UoW.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.scheduled_job import ScheduledJob

JobHandler = Callable[["Container", "ScheduledJob"], Awaitable[None]]

JOB_HANDLERS: dict[str, JobHandler] = {}


def register_handler(job_type: str, handler: JobHandler) -> None:
    """Register a handler for ``job_type``.

    Idempotent — registering the same function under the same name is a
    no-op; registering a *different* function under an already-claimed
    name raises ``RuntimeError``.
    """
    if job_type in JOB_HANDLERS and JOB_HANDLERS[job_type] is not handler:
        raise RuntimeError(
            f"Job handler conflict: {job_type!r} already registered to "
            f"{JOB_HANDLERS[job_type]!r}, got {handler!r}"
        )
    JOB_HANDLERS[job_type] = handler


def get_handler(job_type: str) -> JobHandler | None:
    return JOB_HANDLERS.get(job_type)
