"""Alembic environment.

Reads DATABASE_URL from app settings. Imports `crm.db.base.Base` so that
autogeneration sees all ORM models (none in Plan 1; arrives in Plan 2).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from crm.config import Settings
from crm.db.base import Base
from crm.db.models import (  # noqa: F401  imports register tables on Base.metadata
    Client,
    Contract,
    Document,
    Event,
    FollowUp,
    Lead,
    Project,
    Proposal,
    ScheduledJob,
    User,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Return the URL to migrate against.

    Precedence:
      1. ``sqlalchemy.url`` set on the running Alembic Config — used by
         tests so they don't have to mutate process env to migrate.
      2. ``Settings().database_url`` — used in dev/prod via ``alembic upgrade``.
    """
    configured = context.config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    settings = Settings()  # type: ignore[call-arg]
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", _get_url())
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
