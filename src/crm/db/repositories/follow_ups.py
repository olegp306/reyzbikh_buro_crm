"""FollowUp repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from crm.db.models.enums import FollowUpStatus
from crm.db.models.follow_up import FollowUp
from crm.db.repositories.base import AsyncRepository


class FollowUpRepository(AsyncRepository[FollowUp]):
    model_cls = FollowUp

    async def list_due(self, now: datetime) -> Sequence[FollowUp]:
        """Pending follow-ups whose scheduled_for is in the past."""
        result = await self._session.execute(
            select(FollowUp)
            .where(
                FollowUp.status == FollowUpStatus.pending,
                FollowUp.scheduled_for <= now,
            )
            .order_by(FollowUp.scheduled_for.asc())
        )
        return result.scalars().all()
