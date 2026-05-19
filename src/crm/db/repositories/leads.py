"""Lead repository."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from crm.db.models.enums import LeadStatus
from crm.db.models.lead import Lead
from crm.db.repositories.base import AsyncRepository


class LeadRepository(AsyncRepository[Lead]):
    model_cls = Lead

    async def list_by_status(self, status: LeadStatus) -> Sequence[Lead]:
        result = await self._session.execute(
            select(Lead).where(Lead.status == status).order_by(Lead.created_at.desc())
        )
        return result.scalars().all()
