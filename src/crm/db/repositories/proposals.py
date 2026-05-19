"""Proposal repository."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from crm.db.models.proposal import Proposal
from crm.db.repositories.base import AsyncRepository


class ProposalRepository(AsyncRepository[Proposal]):
    model_cls = Proposal

    async def list_for_lead(self, lead_id: int) -> Sequence[Proposal]:
        result = await self._session.execute(
            select(Proposal).where(Proposal.lead_id == lead_id).order_by(Proposal.version.desc())
        )
        return result.scalars().all()
