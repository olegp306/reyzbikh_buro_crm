from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.use_cases.events import record_event


@pytest.mark.asyncio
async def test_record_event_adds_event_to_session() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    uow = MagicMock()
    uow.session = session

    await record_event(
        uow,
        event_type="lead.created",
        aggregate_type="lead",
        aggregate_id=42,
        payload={"channel": "telegram"},
        actor_user_id=7,
    )

    assert session.add.call_count == 1
    added = session.add.call_args.args[0]
    assert added.event_type == "lead.created"
    assert added.aggregate_type == "lead"
    assert added.aggregate_id == 42
    assert added.payload == {"channel": "telegram"}
    assert added.actor_user_id == 7
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_event_defaults_payload_and_actor() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    uow = MagicMock()
    uow.session = session

    await record_event(
        uow,
        event_type="lead.archived",
        aggregate_type="lead",
        aggregate_id=99,
    )

    added = session.add.call_args.args[0]
    assert added.payload == {}
    assert added.actor_user_id is None


@pytest.mark.asyncio
async def test_record_event_does_not_commit() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    uow = MagicMock()
    uow.session = session

    await record_event(
        uow,
        event_type="lead.created",
        aggregate_type="lead",
        aggregate_id=1,
    )

    session.commit.assert_not_called()
