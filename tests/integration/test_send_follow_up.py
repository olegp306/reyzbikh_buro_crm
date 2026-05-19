"""Integration tests for send_follow_up use case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    FollowUpKind,
    FollowUpStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.follow_up import FollowUp
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.use_cases.send_follow_up import (
    FollowUpNotFoundError,
    send_follow_up,
)


async def _seed_pending_follow_up(container: Container) -> int:
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                status=LeadStatus.proposal_sent,
            )
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.sent,
                generated_text="body",
                scope_summary="scope",
                currency="RUB",
                sent_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
        await uow.commit()
        follow_up = await uow.follow_ups.add(
            FollowUp(
                proposal_id=proposal.id,
                kind=FollowUpKind.status_check,
                scheduled_for=datetime.now(UTC),
                status=FollowUpStatus.pending,
                channel=ChannelKind.telegram,
                message_template="⏰ напомнить про Proposal",
            )
        )
        await uow.commit()
        return follow_up.id


@pytest.mark.integration
async def test_send_follow_up_marks_sent_and_notifies(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

    follow_up_id = await _seed_pending_follow_up(container)
    result = await send_follow_up(container, follow_up_id=follow_up_id)

    assert result.status == FollowUpStatus.sent
    assert result.sent_at is not None
    assert len(sent) == 1
    assert "напомнить" in sent[0]["text"]
    assert sent[0]["reply_markup"] is not None  # outcome keyboard attached

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("follow_up", follow_up_id)
    types = [e.event_type for e in events]
    assert "follow_up.sent" in types

    await container.aclose()


@pytest.mark.integration
async def test_send_follow_up_is_noop_if_already_sent(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

    follow_up_id = await _seed_pending_follow_up(container)
    await send_follow_up(container, follow_up_id=follow_up_id)
    sent.clear()
    # Second call should be silent — no double notification.
    result2 = await send_follow_up(container, follow_up_id=follow_up_id)

    assert result2.status == FollowUpStatus.sent
    assert sent == []

    await container.aclose()


@pytest.mark.integration
async def test_send_follow_up_missing_raises(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    with pytest.raises(FollowUpNotFoundError):
        await send_follow_up(container, follow_up_id=999_999)
    await container.aclose()
