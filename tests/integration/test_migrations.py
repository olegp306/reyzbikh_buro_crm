import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings

EXPECTED_TABLES = {
    "alembic_version",
    "clients",
    "contracts",
    "documents",
    "events",
    "follow_ups",
    "leads",
    "projects",
    "proposals",
    "scheduled_jobs",
    "users",
}


def _alembic_config(settings: Settings) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


@pytest.mark.integration
async def test_full_upgrade_creates_all_domain_tables(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", settings.app_env.value)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", settings.telegram_bot_token)
    monkeypatch.setenv(
        "TELEGRAM_OPERATOR_IDS",
        ",".join(str(i) for i in settings.telegram_operator_ids),
    )
    monkeypatch.setenv("AI_PROVIDER", settings.ai_provider)

    cfg = _alembic_config(settings)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        tables = {row.table_name for row in result}

    assert EXPECTED_TABLES.issubset(tables), f"Missing tables: {EXPECTED_TABLES - tables}"


@pytest.mark.integration
async def test_downgrade_to_base_then_upgrade_again(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", settings.app_env.value)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", settings.telegram_bot_token)
    monkeypatch.setenv(
        "TELEGRAM_OPERATOR_IDS",
        ",".join(str(i) for i in settings.telegram_operator_ids),
    )
    monkeypatch.setenv("AI_PROVIDER", settings.ai_provider)

    cfg = _alembic_config(settings)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "base")

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        tables = {row.table_name for row in result}

    domain_tables = EXPECTED_TABLES - {"alembic_version"}
    assert not (domain_tables & tables), (
        f"Tables left after downgrade base: {domain_tables & tables}"
    )

    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        tables_after = {row.table_name for row in result}

    assert EXPECTED_TABLES.issubset(tables_after)
