"""Worker poll loop.

Picks pending jobs with FOR UPDATE SKIP LOCKED, marks them running, calls
the handler outside the picking transaction, and persists the outcome
(done / rescheduled with backoff / terminally failed) in a separate
transaction.

Concurrency: multiple workers can run safely thanks to
``FOR UPDATE SKIP LOCKED``. Lease timeout (5 min) reclaims jobs left
behind by crashed workers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.orm.attributes import set_committed_value

from crm.scheduler.handlers import get_handler
from crm.scheduler.jobs import LEASE_TIMEOUT, apply_backoff

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.scheduled_job import ScheduledJob

log = structlog.get_logger(__name__)


async def run_worker(
    container: Container,
    *,
    worker_id: str,
    shutdown: asyncio.Event,
) -> None:
    """Run the worker until ``shutdown`` is set."""
    poll_interval = container.settings.worker_poll_interval_seconds
    log.info(
        "worker.starting",
        worker_id=worker_id,
        poll_interval_seconds=poll_interval,
    )

    while not shutdown.is_set():
        try:
            await _reclaim(container)
            picked = await _pick_due_jobs(container, worker_id=worker_id, limit=10)
            for job in picked:
                await _run_one(container, job)
        except Exception as exc:
            log.exception(
                "worker.tick.error",
                worker_id=worker_id,
                error=str(exc),
            )

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
        except TimeoutError:
            continue

    log.info("worker.stopped", worker_id=worker_id)


async def _reclaim(container: Container) -> None:
    now = datetime.now(UTC)
    cutoff = now - LEASE_TIMEOUT
    async with container.uow() as uow:
        rows = await uow.scheduled_jobs.reclaim_stuck(older_than=cutoff, now=now)
        await uow.commit()
    if rows:
        log.warning("worker.reclaimed", count=rows)


async def _pick_due_jobs(container: Container, *, worker_id: str, limit: int) -> list[ScheduledJob]:
    now = datetime.now(UTC)
    async with container.uow() as uow:
        jobs = list(await uow.scheduled_jobs.list_pending_due(now=now, limit=limit))
        for job in jobs:
            prior_attempts = job.attempts
            await uow.scheduled_jobs.mark_running(job.id, worker_id=worker_id, now=now)
            # Sync the in-memory ORM instance with the server-side attempts+1
            # (mark_running is a Core UPDATE so the loaded `job` would still
            # report the OLD value). Downstream `_run_one` compares
            # `job.attempts >= job.max_attempts` and needs the new value.
            # Using set_committed_value (not direct assignment) avoids marking
            # the instance dirty.
            set_committed_value(job, "attempts", prior_attempts + 1)
        await uow.commit()
    return jobs


async def _run_one(container: Container, job: ScheduledJob) -> None:
    handler = get_handler(job.job_type)
    if handler is None:
        await _finalize_unknown_handler(container, job)
        return

    try:
        await handler(container, job)
    except Exception as exc:
        log.warning(
            "worker.handler.failed",
            job_id=job.id,
            job_type=job.job_type,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error=str(exc),
        )
        if job.attempts >= job.max_attempts:
            await _finalize_terminal(container, job, error=str(exc))
        else:
            await _finalize_reschedule(container, job, error=str(exc))
        return

    await _finalize_done(container, job)


async def _finalize_done(container: Container, job: ScheduledJob) -> None:
    now = datetime.now(UTC)
    async with container.uow() as uow:
        await uow.scheduled_jobs.mark_done(job.id, now=now)
        await uow.commit()
    log.info("worker.handler.done", job_id=job.id, job_type=job.job_type)


async def _finalize_reschedule(container: Container, job: ScheduledJob, *, error: str) -> None:
    now = datetime.now(UTC)
    next_run = apply_backoff(job.attempts, now=now)
    async with container.uow() as uow:
        await uow.scheduled_jobs.reschedule(job.id, run_at=next_run, last_error=error, now=now)
        await uow.commit()
    log.info(
        "worker.handler.rescheduled",
        job_id=job.id,
        next_run_at=next_run.isoformat(),
        attempts=job.attempts,
    )


async def _finalize_terminal(container: Container, job: ScheduledJob, *, error: str) -> None:
    now = datetime.now(UTC)
    async with container.uow() as uow:
        await uow.scheduled_jobs.mark_failed_terminal(job.id, last_error=error, now=now)
        await uow.commit()
    log.error(
        "worker.handler.failed_terminal",
        job_id=job.id,
        job_type=job.job_type,
        error=error,
    )
    alert = (
        f"⚠ Job {job.id} ({job.job_type}) сдох окончательно "
        f"после {job.attempts} попыток.\nОшибка: {error[:500]}"  # noqa: RUF001
    )
    await _send_operator_alert(container, job, alert)


async def _finalize_unknown_handler(container: Container, job: ScheduledJob) -> None:
    """No handler registered for this job_type — terminate without retries.

    Distinct path so the operator alert doesn't mention 'N attempts' (there
    weren't any — the job never reached a handler).
    """
    error = f"no handler registered for {job.job_type!r}"
    now = datetime.now(UTC)
    async with container.uow() as uow:
        await uow.scheduled_jobs.mark_failed_terminal(job.id, last_error=error, now=now)
        await uow.commit()
    log.error(
        "worker.handler.unknown_type",
        job_id=job.id,
        job_type=job.job_type,
    )
    alert = (
        f"⚠ Job {job.id} ({job.job_type}): обработчик не зарегистрирован. "
        f"Воркер не знает, как её исполнить — проверь worker.entrypoint."
    )
    await _send_operator_alert(container, job, alert)


async def _send_operator_alert(container: Container, job: ScheduledJob, text: str) -> None:
    ids = container.settings.telegram_operator_ids
    if not ids:
        return
    chat_id = ids[0]
    try:
        await container.telegram_sender.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        log.warning("worker.alert.failed", job_id=job.id, error=str(exc))
