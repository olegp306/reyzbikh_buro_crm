from datetime import UTC, datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update, User

from crm.config import Settings
from crm.container import Container
from crm.entrypoints.bot import register_handlers


def _make_message(text: str, user_id: int) -> Update:
    user = User(id=user_id, is_bot=False, first_name="Op")
    chat = Chat(id=user_id, type="private")
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text=text,
    )
    return Update(update_id=1, message=message)


@pytest.mark.integration
async def test_start_command_replies_to_allowlisted_operator(
    settings: Settings,
    db_clean: None,
) -> None:
    # Operator 111 is in settings.telegram_operator_ids.
    container = Container(settings)
    bot = Bot(token=container.settings.telegram_bot_token)
    dp = Dispatcher()
    register_handlers(dp, container)

    update = _make_message("/start", user_id=111)
    result = await dp.feed_update(bot, update)
    # aiogram returns True/False/None depending on routing. We only care that
    # the handler ran without raising; we'll check side effects via the
    # FakeTelegramSender instead.
    assert result is not None or result is None  # smoke

    sent = container.telegram_sender.sent  # type: ignore[attr-defined]
    assert len(sent) == 1
    assert sent[0].chat_id == 111
    assert "оператор" in sent[0].text.lower() or "operator" in sent[0].text.lower()

    await bot.session.close()
    await container.aclose()


@pytest.mark.integration
async def test_start_command_ignores_non_allowlisted_user(
    settings: Settings,
    db_clean: None,
) -> None:
    container = Container(settings)
    bot = Bot(token=container.settings.telegram_bot_token)
    dp = Dispatcher()
    register_handlers(dp, container)

    update = _make_message("/start", user_id=999)  # not in allowlist
    await dp.feed_update(bot, update)

    sent = container.telegram_sender.sent  # type: ignore[attr-defined]
    assert len(sent) == 0

    await bot.session.close()
    await container.aclose()
