"""Integration test: bot follow_up_outcome callbacks record client response."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
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
from crm.entrypoints.bot import register_handlers


def _container_with_capturing_sender(
    settings: Settings,
) -> tuple[Container, list[dict]]:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]
    return container, sent


async def _seed_sent_follow_up(container: Container) -> tuple[int, int, int]:
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
                sent_at=dt.datetime.now(dt.UTC),
            )
        )
        await uow.commit()
        follow_up = await uow.follow_ups.add(
            FollowUp(
                proposal_id=proposal.id,
                kind=FollowUpKind.status_check,
                scheduled_for=dt.datetime.now(dt.UTC),
                status=FollowUpStatus.sent,
                channel=ChannelKind.telegram,
                message_template="t",
                sent_at=dt.datetime.now(dt.UTC),
            )
        )
        await uow.commit()
        return lead.id, proposal.id, follow_up.id


def _outcome_update(*, operator_id: int, follow_up_id: int, outcome: str) -> Update:
    return Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=operator_id, is_bot=False, first_name="Op"),
            chat_instance="ci-1",
            data=f"follow_up_outcome:{follow_up_id}:{outcome}",
            message=Message(
                message_id=1002,
                date=dt.datetime.now(dt.UTC),
                chat=Chat(id=100, type="private"),
                from_user=User(id=99, is_bot=True, first_name="bot"),
                text="prev",
            ),
        ),
    )


@pytest.mark.integration
async def test_outcome_accepted_transitions_lead(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)
    lead_id, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(
        bot,
        _outcome_update(operator_id=operator_id, follow_up_id=follow_up_id, outcome="accepted"),
    )

    assert len(sent) == 1
    assert "принял" in sent[0]["text"]

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        lead = await uow.leads.get(lead_id)
    assert proposal is not None and proposal.status == ProposalStatus.accepted
    assert lead is not None and lead.status == LeadStatus.accepted

    await container.aclose()


@pytest.mark.integration
async def test_outcome_declined_transitions_lead(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)
    lead_id, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(
        bot,
        _outcome_update(operator_id=operator_id, follow_up_id=follow_up_id, outcome="declined"),
    )

    assert len(sent) == 1
    assert "отказался" in sent[0]["text"]

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        lead = await uow.leads.get(lead_id)
    assert proposal is not None and proposal.status == ProposalStatus.declined
    assert lead is not None and lead.status == LeadStatus.declined

    await container.aclose()


@pytest.mark.integration
async def test_outcome_waiting_leaves_statuses(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)
    lead_id, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(
        bot,
        _outcome_update(operator_id=operator_id, follow_up_id=follow_up_id, outcome="waiting"),
    )

    assert len(sent) == 1
    assert "Ждём" in sent[0]["text"]

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        lead = await uow.leads.get(lead_id)
        follow_up = await uow.follow_ups.get(follow_up_id)
    assert proposal is not None and proposal.status == ProposalStatus.sent
    assert lead is not None and lead.status == LeadStatus.proposal_sent
    assert follow_up is not None and follow_up.result_notes == "(via inline button)"

    await container.aclose()
