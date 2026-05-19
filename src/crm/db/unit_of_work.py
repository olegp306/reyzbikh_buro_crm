"""Unit of Work.

A UoW owns an async SQLAlchemy session for the duration of one logical
operation (typically one use case). Repositories will live as attributes
of the UoW in later plans.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyUnitOfWork:
    """An async Unit of Work backed by SQLAlchemy."""

    session: AsyncSession

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                await self.session.rollback()
        finally:
            await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


@asynccontextmanager
async def uow_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """Convenience context manager.

    Usage:
        async with uow_scope(container.session_factory) as uow:
            ...
            await uow.commit()
    """
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow
