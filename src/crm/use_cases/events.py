"""record_event helper — single entry point for writing to the events log."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from crm.db.models.event import Event

if TYPE_CHECKING:
    from crm.db.unit_of_work import SqlAlchemyUnitOfWork


async def record_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int | None,
    payload: dict[str, Any] | None = None,
    actor_user_id: int | None = None,
) -> Event:
    """Append one row to the events table inside the caller's UoW.

    Does NOT commit. Use cases own the transaction boundary; this helper
    only stages the insert and flushes so `event.id` is populated.

    Args:
        uow: An open SqlAlchemyUnitOfWork.
        event_type: Dotted event name, e.g. ``"lead.created"``.
        aggregate_type: Domain aggregate the event belongs to (``"lead"``,
            ``"proposal"``, ``"project"``, ...). Used for indexed lookups.
        aggregate_id: Primary key of the aggregate, or ``None`` for events
            not tied to a single row (rare).
        payload: Free-form JSONB body. Defaults to ``{}``.
        actor_user_id: The User who triggered the change, or ``None`` for
            system-driven events (worker tick, AI follow-up).

    Returns:
        The persisted ``Event`` instance with ``id`` populated.
    """
    event = Event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload if payload is not None else {},
        actor_user_id=actor_user_id,
    )
    uow.session.add(event)
    await uow.session.flush()
    return event
