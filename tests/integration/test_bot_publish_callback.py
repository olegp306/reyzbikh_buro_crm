"""Integration test: bot 'В Google Doc' callback enqueues the publish job."""  # noqa: RUF002

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.db.models.scheduled_job import ScheduledJob
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


@pytest.mark.integration
async def test_bot_publish_callback_enqueues_job(
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
                status=LeadStatus.qualified,
            )
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.draft,
                generated_text="body",
                scope_summary="scope",
                currency="RUB",
            )
        )
        await uow.commit()
        proposal_id = proposal.id

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=operator_id, is_bot=False, first_name="Op"),
            chat_instance="ci-1",
            data=f"publish_proposal:{proposal_id}",
            message=Message(
                message_id=1002,
                date=dt.datetime.now(dt.UTC),
                chat=Chat(id=100, type="private"),
                from_user=User(id=99, is_bot=True, first_name="bot"),
                text="prev",
            ),
        ),
    )

    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(bot, update)

    assert len(sent) == 1
    assert "Запросил публикацию" in sent[0]["text"]

    async with container.session_factory() as session:
        result = await session.execute(
            select(ScheduledJob).where(ScheduledJob.job_type == "publish_proposal_to_gdoc")
        )
        jobs = list(result.scalars().all())
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.pending
    assert jobs[0].payload["proposal_id"] == proposal_id

    await container.aclose()
