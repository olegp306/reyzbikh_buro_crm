"""Integration test: bot 'Сгенерировать предложение' callback runs generate_proposal."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import ChannelKind, LeadStatus, ProposalStatus
from crm.db.models.lead import Lead
from crm.entrypoints.bot import register_handlers


def _make_callback_update(data: str, *, user_id: int, chat_id: int = 100) -> Update:
    return Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=user_id, is_bot=False, first_name="Op"),
            chat_instance="ci-1",
            data=data,
            message=Message(
                message_id=1002,
                date=dt.datetime.now(dt.UTC),
                chat=Chat(id=chat_id, type="private"),
                from_user=User(id=99, is_bot=True, first_name="bot"),
                text="prev",
            ),
        ),
    )


def _container_with_capturing_sender(settings: Settings) -> tuple[Container, list[dict]]:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]
    return container, sent


@pytest.mark.integration
async def test_bot_propose_callback_creates_proposal(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                summary="kitchen",
                extracted_data={"area_m2": 60},
                status=LeadStatus.qualified,
            )
        )
        await uow.commit()
        lead_id = lead.id

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = _make_callback_update(f"propose_lead:{lead_id}", user_id=operator_id)

    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(bot, update)

    assert len(sent) == 1
    assert "Proposal #" in sent[0]["text"]

    async with container.uow() as uow:
        proposals = await uow.proposals.list_for_lead(lead_id)
    assert len(proposals) == 1
    assert proposals[0].status == ProposalStatus.draft

    await container.aclose()
