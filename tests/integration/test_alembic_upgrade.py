import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings


def _alembic_config(settings: Settings) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


@pytest.mark.integration
async def test_alembic_upgrade_head_runs_clean(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # env.py reads Settings(); inject our test DATABASE_URL.
    monkeypatch.setenv("APP_ENV", settings.app_env.value)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", settings.telegram_bot_token)
    monkeypatch.setenv(
        "TELEGRAM_OPERATOR_IDS",
        ",".join(str(i) for i in settings.telegram_operator_ids),
    )
    monkeypatch.setenv("AI_PROVIDER", settings.ai_provider)

    # Run in a thread: env.py calls asyncio.run() which requires no running loop.
    cfg = _alembic_config(settings)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.one()
    assert row.version_num  # the empty initial revision is recorded
