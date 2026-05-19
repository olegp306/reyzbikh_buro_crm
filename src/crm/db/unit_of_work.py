"""Unit of Work.

A UoW owns an async SQLAlchemy session for the duration of one logical
operation (typically one use case). Repositories live as attributes of the
UoW and share the session — so commits/rollbacks coordinate across aggregates.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crm.db.repositories.clients import ClientRepository
from crm.db.repositories.leads import LeadRepository
from crm.db.repositories.users import UserRepository


class SqlAlchemyUnitOfWork:
    """An async Unit of Work backed by SQLAlchemy."""

    session: AsyncSession
    clients: ClientRepository
    leads: LeadRepository
    users: UserRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        self.clients = ClientRepository(self.session)
        self.leads = LeadRepository(self.session)
        self.users = UserRepository(self.session)
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
            lead = await uow.leads.get(123)
            await uow.commit()
    """
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow
