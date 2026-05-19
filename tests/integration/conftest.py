"""Integration test fixtures.

Spins up a single PostgreSQL container for the whole test session via
testcontainers-python. Each test that takes the `pg_url` fixture gets
a working DSN it can connect to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.postgres import PostgresContainer

from crm.config import AppEnv, Settings
from crm.db.session import build_engine


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def pg_url(pg_container: PostgresContainer) -> str:
    """Return a Postgres URL with the asyncpg driver regardless of testcontainers version."""
    raw = pg_container.get_connection_url()
    for old in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql://",
    ):
        if raw.startswith(old):
            return "postgresql+asyncpg://" + raw[len(old):]
    return raw  # already on +asyncpg


@pytest.fixture
def settings(pg_url: str) -> Settings:
    # Telegram token must match aiogram's regex `\d+:[A-Za-z0-9_-]{35,}`
    # because T10's bot tests pass this value into `Bot(token=...)`.
    return Settings(  # type: ignore[call-arg]
        app_env=AppEnv.test,
        log_level="DEBUG",
        database_url=pg_url,
        telegram_bot_token="123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        telegram_operator_ids=(111,),
        ai_provider="fake",
    )


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(settings)
    try:
        yield eng
    finally:
        await eng.dispose()
