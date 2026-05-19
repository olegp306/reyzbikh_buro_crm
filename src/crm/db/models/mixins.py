"""Reusable column mixins for ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class CreatedAtMixin:
    """Adds an immutable `created_at` column."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TimestampMixin(CreatedAtMixin):
    """Adds `created_at` (from CreatedAtMixin) and `updated_at`.

    `updated_at` is refreshed by SQLAlchemy on every ORM-issued UPDATE.
    Raw SQL UPDATEs would need a DB trigger; we don't issue those.
    """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
