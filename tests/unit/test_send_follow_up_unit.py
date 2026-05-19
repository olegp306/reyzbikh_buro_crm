"""Unit tests for send_follow_up — wiring & idempotency without DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.db.models.enums import FollowUpStatus
from crm.use_cases.send_follow_up import (
    FollowUpNotFoundError,
    send_follow_up,
)


def _stub_uow(follow_up_first, follow_up_second) -> MagicMock:
    """First .get returns follow_up_first; second .get returns follow_up_second."""
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.follow_ups = MagicMock()
    uow.follow_ups.get = AsyncMock(side_effect=[follow_up_first, follow_up_second])
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    return uow


@pytest.mark.asyncio
async def test_send_follow_up_happy_path() -> None:
    follow_up = MagicMock()
    follow_up.id = 1
    follow_up.status = FollowUpStatus.pending
    follow_up.message_template = "hello"
    # Two separate UoW instances are entered — one per TX.
    uow1 = _stub_uow(follow_up, None)
    uow2 = _stub_uow(follow_up, None)
    container = MagicMock()
    container.uow = MagicMock(side_effect=[uow1, uow2])
    container.settings = MagicMock()
    container.settings.telegram_operator_ids = (111,)
    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = AsyncMock()

    result = await send_follow_up(container, follow_up_id=1)

    assert result is follow_up
    assert follow_up.status == FollowUpStatus.sent
    container.telegram_sender.send_message.assert_awaited_once()
    assert uow2.commit.await_count == 1


@pytest.mark.asyncio
async def test_send_follow_up_noop_if_not_pending() -> None:
    follow_up = MagicMock()
    follow_up.id = 1
    follow_up.status = FollowUpStatus.sent
    uow = _stub_uow(follow_up, None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)
    container.settings = MagicMock()
    container.settings.telegram_operator_ids = (111,)
    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = AsyncMock()

    result = await send_follow_up(container, follow_up_id=1)

    assert result is follow_up
    container.telegram_sender.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_follow_up_missing_raises() -> None:
    uow = _stub_uow(None, None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)
    container.settings = MagicMock()
    container.settings.telegram_operator_ids = (111,)

    with pytest.raises(FollowUpNotFoundError):
        await send_follow_up(container, follow_up_id=1)
