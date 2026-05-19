"""ScheduledJob repository.

Worker pick logic (FOR UPDATE SKIP LOCKED) lives here; the worker entrypoint
in Plan 5 will call `claim_due_jobs`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update

from crm.db.models.enums import JobStatus
from crm.db.models.scheduled_job import ScheduledJob
from crm.db.repositories.base import AsyncRepository


class ScheduledJobRepository(AsyncRepository[ScheduledJob]):
    model_cls = ScheduledJob

    async def get_by_idempotency_key(self, key: str) -> ScheduledJob | None:
        result = await self._session.execute(
            select(ScheduledJob).where(ScheduledJob.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def list_pending_due(self, now: datetime, limit: int = 10) -> Sequence[ScheduledJob]:
        result = await self._session.execute(
            select(ScheduledJob)
            .where(
                ScheduledJob.status == JobStatus.pending,
                ScheduledJob.run_at <= now,
            )
            .order_by(ScheduledJob.run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()

    async def mark_running(self, job_id: int, worker_id: str, now: datetime) -> None:
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.running,
                locked_at=now,
                locked_by=worker_id,
                attempts=ScheduledJob.attempts + 1,
            )
        )
