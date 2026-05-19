"""aiogram bot entrypoint.

Translates Telegram events into use-case calls. No business logic here —
only routing, keyboard rendering, and operator allowlist gating.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import ChannelKind
from crm.logging import configure_logging
from crm.use_cases.intake_lead import intake_lead
from crm.use_cases.qualify_lead import (
    LeadCannotQualifyError,
    LeadNotFoundError,
    qualify_lead,
)

log = structlog.get_logger(__name__)

CONFIRM_PREFIX = "confirm_lead:"
EDIT_PREFIX = "edit_lead:"


def _is_operator(container: Container, user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id in container.settings.telegram_operator_ids


def _intake_keyboard(lead_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"{CONFIRM_PREFIX}{lead_id}",
                ),
                InlineKeyboardButton(
                    text="✏ Править",
                    callback_data=f"{EDIT_PREFIX}{lead_id}",
                ),
            ],
        ],
    )


def _format_intake_reply(lead) -> str:
    if lead.extracted_data.get("_extraction_failed"):
        return (
            f"Lead #{lead.id} сохранён, но AI-извлечение упало:\n"
            f"{lead.extracted_data.get('error', '(no detail)')}\n\n"
            "Можно подтвердить вручную или отредактировать."
        )
    return (
        f"Lead #{lead.id}\n\n"
        f"{lead.summary or '(нет сводки)'}\n\n"
        "Подтвердить — статус qualified + создаём Client из извлечённых полей."
    )


def register_handlers(dp: Dispatcher, container: Container) -> None:
    """Register all routers/handlers on the dispatcher."""
    router = Router(name="crm.lead_intake")

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not _is_operator(container, user_id):
            log.info("bot.start.denied", user_id=user_id, reason="not_in_allowlist")
            return
        await container.telegram_sender.send_message(
            chat_id=message.chat.id,
            text="Привет, оператор. CRM на связи.",
        )
        log.info("bot.start.greeted", user_id=user_id)

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not _is_operator(container, user_id):
            log.info("bot.text.denied", user_id=user_id)
            return
        raw = (message.text or "").strip()
        if not raw:
            return

        lead = await intake_lead(
            container,
            raw_text=raw,
            channel=ChannelKind.telegram,
            channel_message_id=f"tg:{message.chat.id}:{message.message_id}",
            operator_user_id=None,
        )

        await container.telegram_sender.send_message(
            chat_id=message.chat.id,
            text=_format_intake_reply(lead),
            reply_markup=_intake_keyboard(lead.id),
        )
        log.info("bot.intake.replied", lead_id=lead.id, status=lead.status.value)

    @router.callback_query(F.data.startswith(CONFIRM_PREFIX))
    async def on_confirm(cb: CallbackQuery) -> None:
        user_id = cb.from_user.id if cb.from_user else None
        if not _is_operator(container, user_id):
            await cb.answer("Нет доступа.")
            return
        try:
            lead_id = int((cb.data or "").removeprefix(CONFIRM_PREFIX))
        except ValueError:
            await cb.answer("Битый callback.")
            return

        try:
            lead = await qualify_lead(
                container,
                lead_id=lead_id,
                operator_user_id=None,
            )
        except LeadNotFoundError:
            await cb.answer(f"Lead {lead_id} не найден.")
            return
        except LeadCannotQualifyError as exc:
            await cb.answer(str(exc), show_alert=True)
            return

        if cb.message is not None:
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=(
                    f"Lead #{lead.id} → qualified."
                    + (
                        f" Создан Client #{lead.client_id}."
                        if lead.client_id
                        else " Client не создан (нет имени в данных)."
                    )
                ),
            )
        await cb.answer()
        log.info("bot.confirm.done", lead_id=lead.id, client_id=lead.client_id)

    @router.callback_query(F.data.startswith(EDIT_PREFIX))
    async def on_edit(cb: CallbackQuery) -> None:
        user_id = cb.from_user.id if cb.from_user else None
        if not _is_operator(container, user_id):
            await cb.answer("Нет доступа.")
            return
        await cb.answer("Редактирование пока не реализовано в v1.", show_alert=True)
        log.info("bot.edit.stub", user_id=user_id)

    dp.include_router(router)


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    register_handlers(dp, container)

    log.info("bot.starting", allowlist_size=len(settings.telegram_operator_ids))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await container.aclose()
        log.info("bot.stopped")


if __name__ == "__main__":
    asyncio.run(run())
