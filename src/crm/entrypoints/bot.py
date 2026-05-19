"""aiogram bot entrypoint.

In Plan 1 the bot only handles `/start` from allowlisted operators. All
business handlers (intake, qualify, propose, ...) arrive in Plan 3.

The bot uses the in-Container `telegram_sender` for outbound messages so
that tests can assert on `FakeTelegramSender.sent`.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging

log = structlog.get_logger(__name__)


def _is_operator(container: Container, user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id in container.settings.telegram_operator_ids


def register_handlers(dp: Dispatcher, container: Container) -> None:
    """Register all routers/handlers on the dispatcher."""
    router = Router(name="crm.plan1")

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not _is_operator(container, user_id):
            log.info(
                "bot.start.denied",
                user_id=user_id,
                reason="not_in_allowlist",
            )
            return

        await container.telegram_sender.send_message(
            chat_id=message.chat.id,
            text="Привет, оператор. CRM на связи.",
        )
        log.info("bot.start.greeted", user_id=user_id)

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
