"""User repository."""

from __future__ import annotations

from sqlalchemy import select

from crm.db.models.user import User
from crm.db.repositories.base import AsyncRepository


class UserRepository(AsyncRepository[User]):
    model_cls = User

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()
