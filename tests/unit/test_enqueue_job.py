"""Unit tests for enqueue_job — idempotency and basic path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.scheduler.jobs import enqueue_job


@pytest.mark.asyncio
async def test_enqueue_job_inserts_new_when_no_key() -> None:
    uow = MagicMock()
    uow.scheduled_jobs = MagicMock()
    uow.scheduled_jobs.get_by_idempotency_key = AsyncMock(return_value=None)
    fake_job = MagicMock()
    fake_job.id = 1
    uow.scheduled_jobs.add = AsyncMock(return_value=fake_job)

    job = await enqueue_job(
        uow,
        job_type="test.job",
        payload={"x": 1},
    )

    assert job is fake_job
    uow.scheduled_jobs.get_by_idempotency_key.assert_not_called()
    uow.scheduled_jobs.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_job_returns_existing_on_idempotency_hit() -> None:
    existing = MagicMock()
    existing.id = 7
    uow = MagicMock()
    uow.scheduled_jobs = MagicMock()
    uow.scheduled_jobs.get_by_idempotency_key = AsyncMock(return_value=existing)
    uow.scheduled_jobs.add = AsyncMock()

    job = await enqueue_job(
        uow,
        job_type="test.job",
        payload={},
        idempotency_key="dup-key",
    )

    assert job is existing
    uow.scheduled_jobs.get_by_idempotency_key.assert_awaited_once_with("dup-key")
    uow.scheduled_jobs.add.assert_not_called()
