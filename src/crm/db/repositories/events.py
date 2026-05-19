"""Event repository. Append-only — only `add` and read queries are used."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from crm.db.models.event import Event
from crm.db.repositories.base import AsyncRepository


class EventRepository(AsyncRepository[Event]):
    model_cls = Event

    async def list_for_aggregate(self, aggregate_type: str, aggregate_id: int) -> Sequence[Event]:
        result = await self._session.execute(
            select(Event)
            .where(
                Event.aggregate_type == aggregate_type,
                Event.aggregate_id == aggregate_id,
            )
            .order_by(Event.occurred_at.asc())
        )
        return result.scalars().all()
