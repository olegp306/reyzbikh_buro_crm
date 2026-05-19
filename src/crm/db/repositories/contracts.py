"""Contract repository."""

from __future__ import annotations

from sqlalchemy import select

from crm.db.models.contract import Contract
from crm.db.repositories.base import AsyncRepository


class ContractRepository(AsyncRepository[Contract]):
    model_cls = Contract

    async def get_by_number(self, contract_number: str) -> Contract | None:
        result = await self._session.execute(
            select(Contract).where(Contract.contract_number == contract_number)
        )
        return result.scalar_one_or_none()
