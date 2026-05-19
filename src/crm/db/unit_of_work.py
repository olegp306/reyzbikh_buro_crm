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
from crm.db.repositories.contracts import ContractRepository
from crm.db.repositories.documents import DocumentRepository
from crm.db.repositories.events import EventRepository
from crm.db.repositories.follow_ups import FollowUpRepository
from crm.db.repositories.leads import LeadRepository
from crm.db.repositories.projects import ProjectRepository
from crm.db.repositories.proposals import ProposalRepository
from crm.db.repositories.scheduled_jobs import ScheduledJobRepository
from crm.db.repositories.users import UserRepository


class SqlAlchemyUnitOfWork:
    """An async Unit of Work backed by SQLAlchemy."""

    session: AsyncSession
    clients: ClientRepository
    contracts: ContractRepository
    documents: DocumentRepository
    events: EventRepository
    follow_ups: FollowUpRepository
    leads: LeadRepository
    projects: ProjectRepository
    proposals: ProposalRepository
    scheduled_jobs: ScheduledJobRepository
    users: UserRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        self.clients = ClientRepository(self.session)
        self.contracts = ContractRepository(self.session)
        self.documents = DocumentRepository(self.session)
        self.events = EventRepository(self.session)
        self.follow_ups = FollowUpRepository(self.session)
        self.leads = LeadRepository(self.session)
        self.projects = ProjectRepository(self.session)
        self.proposals = ProposalRepository(self.session)
        self.scheduled_jobs = ScheduledJobRepository(self.session)
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
