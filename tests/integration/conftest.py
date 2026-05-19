"""Integration test fixtures.

- Session-scoped Postgres testcontainer (one boot per pytest session).
- Session-scoped Alembic upgrade — runs once after the container is up.
- Function-scoped `db_clean` truncates all domain tables before each test,
  giving every test a deterministic starting point even though they share
  the underlying database.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.postgres import PostgresContainer

from crm.config import AppEnv, Settings
from crm.db.session import build_engine

_DOMAIN_TABLES: tuple[str, ...] = (
    "events",
    "scheduled_jobs",
    "documents",
    "follow_ups",
    "contracts",
    "proposals",
    "projects",
    "leads",
    "clients",
    "users",
)


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def pg_url(pg_container: PostgresContainer) -> str:
    raw = pg_container.get_connection_url()
    for old in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql://",
    ):
        if raw.startswith(old):
            return "postgresql+asyncpg://" + raw[len(old) :]
    return raw


@pytest.fixture
def settings(pg_url: str) -> Settings:
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


@pytest_asyncio.fixture(scope="session")
async def _migrated(pg_url: str) -> str:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    return pg_url


@pytest_asyncio.fixture
async def db_clean(engine: AsyncEngine, _migrated: str) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE TABLE {', '.join(_DOMAIN_TABLES)} RESTART IDENTITY CASCADE")
        )
    yield
