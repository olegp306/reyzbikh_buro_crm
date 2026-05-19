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

    async def mark_done(self, job_id: int, *, now: datetime) -> None:
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.done,
                locked_at=None,
                locked_by=None,
                last_error=None,
                updated_at=now,
            )
        )

    async def reschedule(
        self,
        job_id: int,
        *,
        run_at: datetime,
        last_error: str,
        now: datetime,
    ) -> None:
        """Mark a failed attempt and reschedule (status=pending, run_at later)."""
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.pending,
                run_at=run_at,
                last_error=last_error[:2000],
                locked_at=None,
                locked_by=None,
                updated_at=now,
            )
        )

    async def mark_failed_terminal(self, job_id: int, *, last_error: str, now: datetime) -> None:
        """Job exhausted ``max_attempts`` — terminal failure."""
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.failed,
                last_error=last_error[:2000],
                locked_at=None,
                locked_by=None,
                updated_at=now,
            )
        )

    async def reclaim_stuck(self, *, older_than: datetime, now: datetime) -> int:
        """Return jobs locked-running before ``older_than`` to ``pending``.

        Returns the number of rows affected.
        """
        result = await self._session.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.status == JobStatus.running,
                ScheduledJob.locked_at < older_than,
            )
            .values(
                status=JobStatus.pending,
                locked_at=None,
                locked_by=None,
                updated_at=now,
            )
        )
        return result.rowcount or 0
