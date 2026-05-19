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
from crm.use_cases.send_follow_up import FOLLOW_UP_OUTCOME_PREFIX

log = structlog.get_logger(__name__)

CONFIRM_PREFIX = "confirm_lead:"
EDIT_PREFIX = "edit_lead:"
PROPOSE_PREFIX = "propose_lead:"
PUBLISH_PROPOSAL_PREFIX = "publish_proposal:"
MARK_SENT_PREFIX = "mark_sent:"
# FOLLOW_UP_OUTCOME_PREFIX re-exported from crm.use_cases.send_follow_up
# so the bot router and the worker keyboard builder can't drift apart.


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
            text = f"Lead #{lead.id} → qualified." + (
                f" Создан Client #{lead.client_id}."
                if lead.client_id
                else " Client не создан (нет имени в данных)."
            )
            propose_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📝 Сгенерировать предложение",
                            callback_data=f"{PROPOSE_PREFIX}{lead.id}",
                        ),
                    ],
                ],
            )
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=text,
                reply_markup=propose_kb,
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

    @router.callback_query(F.data.startswith(PROPOSE_PREFIX))
    async def on_propose(cb: CallbackQuery) -> None:
        user_id = cb.from_user.id if cb.from_user else None
        if not _is_operator(container, user_id):
            await cb.answer("Нет доступа.")
            return
        try:
            lead_id = int((cb.data or "").removeprefix(PROPOSE_PREFIX))
        except ValueError:
            await cb.answer("Битый callback.")
            return

        from crm.use_cases.generate_proposal import (
            LeadNotQualifiedError,
            generate_proposal,
        )

        try:
            proposal = await generate_proposal(container, lead_id=lead_id, operator_user_id=None)
        except LeadNotFoundError:
            await cb.answer(f"Lead {lead_id} не найден.")
            return
        except LeadNotQualifiedError as exc:
            await cb.answer(str(exc), show_alert=True)
            return

        body_preview = (proposal.generated_text or "(AI ничего не вернул)")[:500]
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📄 В Google Doc",  # noqa: RUF001
                        callback_data=f"publish_proposal:{proposal.id}",
                    ),
                ],
            ],
        )
        if cb.message is not None:
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=(
                    f"Proposal #{proposal.id} (draft) для lead #{proposal.lead_id}:\n\n"
                    f"{body_preview}"
                ),
                reply_markup=kb,
            )
        await cb.answer()

    @router.callback_query(F.data.startswith(PUBLISH_PROPOSAL_PREFIX))
    async def on_publish_proposal(cb: CallbackQuery) -> None:
        user_id = cb.from_user.id if cb.from_user else None
        if not _is_operator(container, user_id):
            await cb.answer("Нет доступа.")
            return
        try:
            proposal_id = int((cb.data or "").removeprefix(PUBLISH_PROPOSAL_PREFIX))
        except ValueError:
            await cb.answer("Битый callback.")
            return

        from crm.use_cases.publish_proposal_to_gdoc import (
            ProposalNotFoundError,
            ProposalNotReadyError,
            publish_proposal_to_gdoc,
        )

        try:
            job = await publish_proposal_to_gdoc(
                container, proposal_id=proposal_id, operator_user_id=None
            )
        except ProposalNotFoundError:
            await cb.answer(f"Proposal {proposal_id} не найден.")
            return
        except ProposalNotReadyError as exc:
            await cb.answer(str(exc), show_alert=True)
            return

        if cb.message is not None:
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=(
                    f"⏳ Запросил публикацию Proposal #{proposal_id} в GDoc "
                    f"(job #{job.id}). Воркер скоро отработает."
                ),
            )
        await cb.answer()
        log.info(
            "bot.publish_proposal.enqueued",
            proposal_id=proposal_id,
            job_id=job.id,
        )

    @router.callback_query(F.data.startswith(MARK_SENT_PREFIX))
    async def on_mark_sent(cb: CallbackQuery) -> None:
        user_id = cb.from_user.id if cb.from_user else None
        if not _is_operator(container, user_id):
            await cb.answer("Нет доступа.")
            return
        try:
            proposal_id = int((cb.data or "").removeprefix(MARK_SENT_PREFIX))
        except ValueError:
            await cb.answer("Битый callback.")
            return

        from crm.use_cases.mark_proposal_sent import (
            ProposalNotFoundError,
            ProposalNotInDraftError,
            mark_proposal_sent,
        )

        try:
            result = await mark_proposal_sent(
                container, proposal_id=proposal_id, operator_user_id=None
            )
        except ProposalNotFoundError:
            await cb.answer(f"Proposal {proposal_id} не найден.")
            return
        except ProposalNotInDraftError as exc:
            await cb.answer(str(exc), show_alert=True)
            return
        except RuntimeError as exc:
            log.exception(
                "bot.mark_sent.runtime_error",
                proposal_id=proposal_id,
                error=str(exc),
            )
            await cb.answer("Внутренняя ошибка, проверь логи.", show_alert=True)
            return

        if cb.message is not None:
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=(
                    f"✅ Proposal #{result.proposal.id} → sent. "
                    f"Напоминание через 3 дня (FollowUp #{result.follow_up.id})."
                ),
            )
        await cb.answer()
        log.info(
            "bot.mark_sent.done",
            proposal_id=proposal_id,
            follow_up_id=result.follow_up.id,
        )

    @router.callback_query(F.data.startswith(FOLLOW_UP_OUTCOME_PREFIX))
    async def on_follow_up_outcome(cb: CallbackQuery) -> None:
        user_id = cb.from_user.id if cb.from_user else None
        if not _is_operator(container, user_id):
            await cb.answer("Нет доступа.")
            return

        raw = (cb.data or "").removeprefix(FOLLOW_UP_OUTCOME_PREFIX)
        try:
            id_part, outcome_part = raw.split(":", 1)
            follow_up_id = int(id_part)
        except ValueError:
            await cb.answer("Битый callback.")
            return

        from crm.use_cases.record_follow_up_result import (
            FollowUpNotFoundError,
            FollowUpNotSentError,
            FollowUpOutcome,
            record_follow_up_result,
        )

        try:
            outcome = FollowUpOutcome(outcome_part)
        except ValueError:
            await cb.answer(f"Неизвестный outcome: {outcome_part}.")
            return

        try:
            await record_follow_up_result(
                container,
                follow_up_id=follow_up_id,
                outcome=outcome,
                notes="(via inline button)",
                operator_user_id=None,
            )
        except FollowUpNotFoundError:
            await cb.answer(f"FollowUp {follow_up_id} не найден.")
            return
        except FollowUpNotSentError as exc:
            await cb.answer(str(exc), show_alert=True)
            return
        except RuntimeError as exc:
            log.exception(
                "bot.follow_up_outcome.runtime_error",
                follow_up_id=follow_up_id,
                error=str(exc),
            )
            await cb.answer("Внутренняя ошибка, проверь логи.", show_alert=True)
            return

        outcome_label = {
            FollowUpOutcome.accepted: "✅ Клиент принял",
            FollowUpOutcome.declined: "❌ Клиент отказался",
            FollowUpOutcome.waiting: "💬 Ждём ещё",
        }[outcome]
        if cb.message is not None:
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=f"{outcome_label} — записано (FollowUp #{follow_up_id}).",
            )
        await cb.answer()
        log.info(
            "bot.follow_up_outcome.done",
            follow_up_id=follow_up_id,
            outcome=outcome.value,
        )

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
