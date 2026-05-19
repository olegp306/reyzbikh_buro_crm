"""Generic async repository base."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class AsyncRepository(Generic[ModelT]):  # noqa: UP046
    """CRUD primitives shared by every repository.

    Subclasses set `model_cls` and add domain-specific queries.
    """

    model_cls: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: int) -> ModelT | None:
        result = await self._session.execute(
            select(self.model_cls).where(self.model_cls.id == entity_id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self._session.delete(entity)
        await self._session.flush()
