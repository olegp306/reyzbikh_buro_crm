"""Integration tests for the worker poll loop (end-to-end)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import JobStatus
from crm.db.models.scheduled_job import ScheduledJob
from crm.scheduler.handlers import JOB_HANDLERS, register_handler
from crm.scheduler.runner import _pick_due_jobs, _run_one, run_worker


@pytest.fixture(autouse=True)
def _clean_handlers():
    JOB_HANDLERS.clear()
    yield
    JOB_HANDLERS.clear()


@pytest.mark.integration
async def test_worker_picks_due_job_and_marks_done(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    called: list[int] = []

    async def _handler(c: Container, job: ScheduledJob) -> None:
        called.append(job.id)

    register_handler("test.success", _handler)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="test.success",
                payload={"x": 1},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=5,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    assert picked[0].id == job_id
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.done
    assert called == [job_id]

    await container.aclose()


@pytest.mark.integration
async def test_worker_reschedules_on_handler_exception(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)

    async def _broken(c: Container, job: ScheduledJob) -> None:
        raise RuntimeError("boom")

    register_handler("test.broken", _broken)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="test.broken",
                payload={},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=3,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.pending  # rescheduled
    assert reloaded.attempts == 1
    assert reloaded.last_error == "boom"
    assert reloaded.run_at > datetime.now(UTC)

    await container.aclose()


@pytest.mark.integration
async def test_worker_marks_failed_terminal_after_max_attempts(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

    async def _broken(c: Container, job: ScheduledJob) -> None:
        raise RuntimeError("permanent")

    register_handler("test.broken", _broken)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="test.broken",
                payload={},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                attempts=2,  # mark_running will bump to 3
                max_attempts=3,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.failed
    assert reloaded.last_error == "permanent"
    assert len(sent) == 1
    assert "сдох" in sent[0]["text"]

    await container.aclose()


@pytest.mark.integration
async def test_worker_unknown_job_type_marks_failed(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="nope.unknown",
                payload={},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=3,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.failed
    assert "no handler" in (reloaded.last_error or "")

    await container.aclose()


@pytest.mark.integration
async def test_run_worker_stops_on_shutdown_event(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    shutdown = asyncio.Event()
    settings.worker_poll_interval_seconds = 0.05  # type: ignore[misc]

    async def _stopper():
        await asyncio.sleep(0.2)
        shutdown.set()

    await asyncio.gather(
        run_worker(container, worker_id="t1", shutdown=shutdown),
        _stopper(),
    )

    await container.aclose()
