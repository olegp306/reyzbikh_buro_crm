"""Project repository."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from crm.db.models.enums import ProjectStatus
from crm.db.models.project import Project
from crm.db.repositories.base import AsyncRepository


class ProjectRepository(AsyncRepository[Project]):
    model_cls = Project

    async def list_active(self) -> Sequence[Project]:
        active_states = (
            ProjectStatus.in_progress,
            ProjectStatus.contract_signed,
            ProjectStatus.paused,
        )
        result = await self._session.execute(
            select(Project)
            .where(Project.status.in_(active_states))
            .order_by(Project.created_at.desc())
        )
        return result.scalars().all()
