"""Integration tests for the lead intake bot handlers."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import ChannelKind, LeadStatus
from crm.db.models.lead import Lead
from crm.entrypoints.bot import register_handlers


def _make_text_update(text: str, *, user_id: int, msg_id: int = 1001, chat_id: int = 100) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=msg_id,
            date=dt.datetime.now(dt.UTC),
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Op"),
            text=text,
        ),
    )


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


def _make_bot_stub() -> AsyncMock:
    # AsyncMock: CallbackQuery.answer() does `await bot(method)`.
    bot = AsyncMock()
    bot.id = 99
    bot.session = MagicMock()
    bot.session.close = AsyncMock()
    return bot


@pytest.mark.integration
async def test_bot_text_message_runs_intake_and_shows_keyboard(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = _make_text_update("Иван, дом 200 м2", user_id=operator_id)
    await dp.feed_update(_make_bot_stub(), update)

    assert len(sent) == 1
    payload = sent[0]
    assert "Lead #" in payload["text"]
    assert isinstance(payload["reply_markup"], InlineKeyboardMarkup)

    await container.aclose()


@pytest.mark.integration
async def test_bot_text_from_non_operator_is_ignored(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)

    dp = Dispatcher()
    register_handlers(dp, container)

    update = _make_text_update("hi", user_id=987654321)
    await dp.feed_update(_make_bot_stub(), update)

    assert sent == []
    await container.aclose()


@pytest.mark.integration
async def test_bot_confirm_callback_qualifies_lead(
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
                status=LeadStatus.qualifying,
                extracted_data={"full_name": "Тест"},
            )
        )
        await uow.commit()
        lead_id = lead.id

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = _make_callback_update(f"confirm_lead:{lead_id}", user_id=operator_id)
    await dp.feed_update(_make_bot_stub(), update)

    assert len(sent) == 1
    assert f"Lead #{lead_id}" in sent[0]["text"]
    assert "qualified" in sent[0]["text"]

    async with container.uow() as uow:
        loaded = await uow.leads.get(lead_id)
    assert loaded is not None
    assert loaded.status == LeadStatus.qualified
    assert loaded.client_id is not None

    await container.aclose()
