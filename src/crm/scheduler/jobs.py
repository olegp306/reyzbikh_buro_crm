"""Job queue primitives — enqueue and backoff.

Spec §6.2. Plain functions; take an open UoW.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from crm.db.models.enums import JobStatus
from crm.db.models.scheduled_job import ScheduledJob

if TYPE_CHECKING:
    from crm.db.unit_of_work import SqlAlchemyUnitOfWork

log = structlog.get_logger(__name__)

LEASE_TIMEOUT: timedelta = timedelta(minutes=5)

_BACKOFF_BASE: timedelta = timedelta(seconds=60)
_BACKOFF_JITTER_MAX: timedelta = timedelta(seconds=15)


async def enqueue_job(
    uow: SqlAlchemyUnitOfWork,
    *,
    job_type: str,
    payload: dict[str, Any],
    run_at: datetime | None = None,
    max_attempts: int = 5,
    idempotency_key: str | None = None,
) -> ScheduledJob:
    """Insert a row into ``scheduled_jobs`` inside the caller's UoW.

    If ``idempotency_key`` is provided and a job with this key already
    exists, returns the existing job WITHOUT inserting a duplicate.

    Does NOT commit. Use cases own the transaction boundary.
    """
    if run_at is None:
        run_at = datetime.now(UTC)

    if idempotency_key is not None:
        existing = await uow.scheduled_jobs.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            log.info(
                "scheduler.enqueue_job.idempotency_hit",
                job_type=job_type,
                existing_job_id=existing.id,
                key=idempotency_key,
            )
            return existing

    job = await uow.scheduled_jobs.add(
        ScheduledJob(
            job_type=job_type,
            payload=payload,
            run_at=run_at,
            status=JobStatus.pending,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        )
    )
    log.info(
        "scheduler.enqueue_job.created",
        job_id=job.id,
        job_type=job_type,
        run_at=run_at.isoformat(),
    )
    return job


def apply_backoff(attempts: int, *, now: datetime | None = None) -> datetime:
    """Return the next ``run_at`` after ``attempts`` failed tries.

    Formula: ``now + BASE * 2**attempts + uniform(0, JITTER_MAX)``.
    """
    if now is None:
        now = datetime.now(UTC)
    multiplier = 2 ** max(0, attempts)
    jitter = timedelta(seconds=random.uniform(0, _BACKOFF_JITTER_MAX.total_seconds()))
    return now + _BACKOFF_BASE * multiplier + jitter
