"""ScheduledJob ORM model. Postgres-backed worker queue.

Worker uses `SELECT ... FOR UPDATE SKIP LOCKED` to pick pending jobs.
`idempotency_key` is a partial unique index (only non-null values are unique)
so use cases can prevent enqueuing duplicates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import JobStatus
from crm.db.models.mixins import TimestampMixin


class ScheduledJob(TimestampMixin, Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", create_type=True),
        nullable=False,
        default=JobStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ux_scheduled_jobs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        Index(
            "ix_scheduled_jobs_pending_run_at",
            "run_at",
            postgresql_where="status = 'pending'",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduledJob id={self.id} type={self.job_type} "
            f"status={self.status} run_at={self.run_at.isoformat() if self.run_at else None}>"
        )
