"""Client repository."""

from __future__ import annotations

from sqlalchemy import select

from crm.db.models.client import Client
from crm.db.repositories.base import AsyncRepository


class ClientRepository(AsyncRepository[Client]):
    model_cls = Client

    async def get_by_telegram_id(self, telegram_id: int) -> Client | None:
        result = await self._session.execute(
            select(Client).where(Client.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()
