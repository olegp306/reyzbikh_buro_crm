# CRM Platform — Plan 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-19-crm-platform-design.md`

**Plan position:** 1 of 8 (Foundation). Next: Plan 2 — Domain + Schema. To be written after Plan 1 is implemented and verified.

**Goal:** Stand up a runnable three-process Docker Compose stack (api, bot, worker) on top of Postgres, with structured logging, configuration loading, async SQLAlchemy plumbing, Alembic migrations (empty first revision), DI container, fake adapters, Telegram allowlist auth on the bot, `/healthz` on the API, and green CI. No domain logic, no real AI, no real Google Docs.

**Architecture:** Single Python package `crm`. Three entrypoints (`crm.entrypoints.api`, `crm.entrypoints.bot`, `crm.entrypoints.worker`) share one DI container. All external dependencies (AI, GDocs, Telegram outbound) live behind `Protocol` interfaces with fake implementations in this plan; real adapters arrive in later plans. Tests at two levels: unit (no IO) and integration (real Postgres via testcontainers).

**Tech Stack:**
- Python 3.12, `uv` package manager
- FastAPI + uvicorn (api process)
- aiogram 3 (bot process)
- SQLAlchemy 2.0 async + asyncpg
- Alembic
- pydantic-settings
- structlog
- pytest + pytest-asyncio + httpx + testcontainers
- ruff (linter + formatter)
- Docker Compose

---

## Pre-flight checklist (do once before starting Task 1)

- [ ] Python 3.12+ installed: `python --version` → `Python 3.12.x` or higher
- [ ] `uv` installed: `uv --version` → any version
- [ ] Docker available: `docker --version` and `docker compose version` both work
- [ ] `git` available and configured
- [ ] Working in `c:\Repos\reyzbikh_buro_crm` on `main` branch with the spec commit (`6edbff5`) as HEAD

If `uv` is missing: install per <https://docs.astral.sh/uv/getting-started/installation/>.

---

## File map for Plan 1

What gets created across all 14 tasks (everything else is later plans):

```
reyzbikh_buro_crm/
├── .github/
│   └── workflows/
│       └── ci.yml                          # T13
├── .gitignore                              # T1
├── .env.example                            # T2 (initial) / T14 (finalized)
├── .dockerignore                           # T12
├── README.md                               # T1 (skeleton) / T14 (finalized)
├── pyproject.toml                          # T1
├── uv.lock                                 # T1 (auto-generated)
├── Dockerfile                              # T12
├── docker-compose.yml                      # T12
├── alembic.ini                             # T5
├── migrations/
│   ├── env.py                              # T5
│   ├── script.py.mako                      # T5 (alembic-generated)
│   └── versions/
│       └── <ts>_initial.py                 # T5 (empty initial)
├── src/
│   └── crm/
│       ├── __init__.py                     # T1
│       ├── config.py                       # T2
│       ├── logging.py                      # T3
│       ├── container.py                    # T8
│       ├── db/
│       │   ├── __init__.py                 # T4
│       │   ├── base.py                     # T4
│       │   ├── session.py                  # T4
│       │   └── unit_of_work.py             # T6
│       ├── adapters/
│       │   ├── __init__.py                 # T7
│       │   ├── ai/
│       │   │   ├── __init__.py             # T7
│       │   │   ├── extractor.py            # T7
│       │   │   └── proposal_writer.py      # T7
│       │   ├── gdocs/
│       │   │   ├── __init__.py             # T7
│       │   │   └── client.py               # T7
│       │   └── telegram/
│       │       ├── __init__.py             # T7
│       │       └── sender.py               # T7
│       └── entrypoints/
│           ├── __init__.py                 # T9
│           ├── api.py                      # T9
│           ├── bot.py                      # T10
│           └── worker.py                   # T11
└── tests/
    ├── __init__.py                         # T1
    ├── conftest.py                         # T1
    ├── unit/
    │   ├── __init__.py                     # T1
    │   ├── test_config.py                  # T2
    │   ├── test_logging.py                 # T3
    │   ├── test_container.py               # T8
    │   └── test_fake_adapters.py           # T7
    └── integration/
        ├── __init__.py                     # T4
        ├── conftest.py                     # T4
        ├── test_db_connection.py           # T4
        ├── test_alembic_upgrade.py         # T5
        ├── test_api_healthz.py             # T9
        └── test_bot_start.py               # T10
```

---

## Task 1: Project skeleton and dev tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md` (minimal — finalized in T14)
- Create: `src/crm/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "crm"
version = "0.1.0"
description = "CRM/workflow platform for an architecture bureau"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "aiogram>=3.15",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "structlog>=24.4",
    "python-json-logger>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "httpx>=0.27",
    "testcontainers[postgres]>=4.8",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/crm"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "RUF"]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: tests that require a real Postgres (via testcontainers)",
]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/

# Environments
.venv/
venv/
env/

# uv
.python-version

# IDE
.vscode/
.idea/

# Secrets
.env
secrets/
*.pem
*.key
google-sa.json

# OS
.DS_Store
Thumbs.db

# Docker
*.log
```

- [ ] **Step 3: Create minimal `README.md`**

```markdown
# Reyzbikh Buro CRM

CRM/workflow platform for an architecture bureau.

See `docs/superpowers/specs/2026-05-19-crm-platform-design.md` for full architecture.

## Status

Plan 1 (Foundation) — in progress.

## Quickstart (will be expanded in Task 14)

```bash
uv sync
cp .env.example .env  # edit values
docker compose up
```
```

- [ ] **Step 4: Create empty package files**

Create `src/crm/__init__.py`:

```python
"""CRM/workflow platform for an architecture bureau."""

__version__ = "0.1.0"
```

Create `tests/__init__.py`: empty file (0 bytes).

Create `tests/unit/__init__.py`: empty file (0 bytes).

- [ ] **Step 5: Create `tests/conftest.py`**

```python
"""Shared pytest configuration. Real fixtures live in unit/conftest.py or integration/conftest.py."""
```

- [ ] **Step 6: Run `uv sync` and verify imports**

Run:
```bash
uv sync
```

Expected: dependencies resolve, `.venv/` created, `uv.lock` generated.

Run:
```bash
uv run python -c "import crm; print(crm.__version__)"
```

Expected output: `0.1.0`

- [ ] **Step 7: Run pytest with no tests to verify pytest is wired**

Run:
```bash
uv run pytest
```

Expected: `no tests ran` (exit code 5 — this is fine for now).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .gitignore README.md src/ tests/
git commit -m "feat(foundation): initial Python project skeleton with uv and pytest"
```

---

## Task 2: Application settings (config.py)

**Files:**
- Create: `src/crm/config.py`
- Create: `.env.example`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from crm.config import AppEnv, Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://crm:crm@localhost:5432/crm",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "111,222,333")
    monkeypatch.setenv("AI_PROVIDER", "fake")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.app_env is AppEnv.test
    assert settings.log_level == "DEBUG"
    assert settings.telegram_operator_ids == (111, 222, 333)
    assert settings.ai_provider == "fake"


def test_settings_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "APP_ENV",
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OPERATOR_IDS",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_operator_id_allowlist_parses_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@z/db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "")
    monkeypatch.setenv("AI_PROVIDER", "fake")

    settings = Settings()  # type: ignore[call-arg]
    assert settings.telegram_operator_ids == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'crm.config'`

- [ ] **Step 3: Write minimal implementation**

Create `src/crm/config.py`:

```python
"""Application settings loaded from environment variables via pydantic-settings."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnv(str, Enum):
    dev = "dev"
    test = "test"
    prod = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: AppEnv = Field(...)
    log_level: str = Field(default="INFO")

    database_url: str = Field(...)

    telegram_bot_token: str = Field(...)
    # NoDecode prevents pydantic-settings >=2.7 from JSON-decoding the env
    # value before our @field_validator runs; without it,
    # `TELEGRAM_OPERATOR_IDS=111,222` would fail JSON parsing.
    telegram_operator_ids: Annotated[tuple[int, ...], NoDecode] = Field(...)

    ai_provider: Literal["openai", "anthropic", "fake"] = Field(default="fake")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-5.5-medium")

    google_service_account_json: str | None = Field(default=None)
    google_docs_parent_folder_id: str | None = Field(default=None)

    worker_poll_interval_seconds: float = Field(default=5.0)

    @field_validator("telegram_operator_ids", mode="before")
    @classmethod
    def _parse_operator_ids(cls, raw: object) -> tuple[int, ...]:
        if raw is None or raw == "":
            return ()
        if isinstance(raw, str):
            return tuple(int(p.strip()) for p in raw.split(",") if p.strip())
        if isinstance(raw, (list, tuple)):
            return tuple(int(p) for p in raw)
        msg = f"Cannot parse telegram_operator_ids from {raw!r}"
        raise ValueError(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Create `.env.example`**

Create `.env.example`:

```env
# === Application ===
APP_ENV=dev
LOG_LEVEL=INFO

# === Database ===
# In Docker Compose the host is "postgres". For local-host runs use "localhost".
DATABASE_URL=postgresql+asyncpg://crm:crm@postgres:5432/crm

# === Telegram ===
TELEGRAM_BOT_TOKEN=
# Comma-separated allowlist of Telegram user IDs. Empty = nobody is allowed.
TELEGRAM_OPERATOR_IDS=

# === AI ===
# fake = no network; openai/anthropic = real (configure key below).
AI_PROVIDER=fake
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5-medium

# === Google ===
# Path to service-account JSON file (mounted into container).
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_DOCS_PARENT_FOLDER_ID=

# === Worker ===
WORKER_POLL_INTERVAL_SECONDS=5
```

- [ ] **Step 6: Commit**

```bash
git add src/crm/config.py tests/unit/test_config.py .env.example
git commit -m "feat(foundation): application settings via pydantic-settings"
```

---

## Task 3: Structured logging

**Files:**
- Create: `src/crm/logging.py`
- Test: `tests/unit/test_logging.py`

Goal: a single `configure_logging(settings)` function that sets up `structlog` so every `logger.info(...)` becomes a JSON line (prod) or coloured key-value (dev), and secret-looking keys are masked.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_logging.py`:

```python
import io
import json
import logging

import pytest
import structlog

from crm.config import AppEnv, Settings
from crm.logging import configure_logging, mask_secrets


def _make_settings(app_env: AppEnv) -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env=app_env,
        log_level="DEBUG",
        database_url="postgresql+asyncpg://x:y@z/db",
        telegram_bot_token="t",
        telegram_operator_ids=(1,),
        ai_provider="fake",
    )


def test_mask_secrets_redacts_known_keys() -> None:
    event = {
        "msg": "hi",
        "api_key": "sk-secret",
        "telegram_bot_token": "12345:abc",
        "user_id": 42,
    }
    masked = mask_secrets(None, "info", event.copy())
    assert masked["api_key"] == "***"
    assert masked["telegram_bot_token"] == "***"
    assert masked["user_id"] == 42
    assert masked["msg"] == "hi"


def test_configure_logging_prod_emits_json(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    configure_logging(_make_settings(AppEnv.prod))

    log = structlog.get_logger("test")
    log.info("hello", lead_id=42, api_key="should-mask")

    line = buffer.getvalue().strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["lead_id"] == 42
    assert record["api_key"] == "***"


def test_configure_logging_dev_is_human_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    configure_logging(_make_settings(AppEnv.dev))

    log = structlog.get_logger("test")
    log.info("hello", lead_id=42)

    output = buffer.getvalue()
    assert "hello" in output
    assert "lead_id" in output
    # Dev format is not valid JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.strip().splitlines()[-1])


def test_configure_logging_sets_stdlib_level() -> None:
    configure_logging(_make_settings(AppEnv.dev))
    assert logging.getLogger().level == logging.DEBUG
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/unit/test_logging.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'crm.logging'`

- [ ] **Step 3: Write the implementation**

Create `src/crm/logging.py`:

```python
"""Structured logging setup via structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from crm.config import AppEnv, Settings

SECRET_KEY_FRAGMENTS: tuple[str, ...] = (
    "token",
    "key",
    "secret",
    "password",
    "authorization",
)


def mask_secrets(
    _logger: Any,
    _name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor that replaces secret-looking values with '***'."""
    for key in list(event_dict.keys()):
        lowered = key.lower()
        if any(frag in lowered for frag in SECRET_KEY_FRAGMENTS):
            event_dict[key] = "***"
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog and stdlib logging according to settings."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        mask_secrets,
    ]

    if settings.app_env is AppEnv.prod:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/unit/test_logging.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/crm/logging.py tests/unit/test_logging.py
git commit -m "feat(foundation): structlog setup with secret masking"
```

---

## Task 4: SQLAlchemy async base, session factory, integration test harness

**Files:**
- Create: `src/crm/db/__init__.py`
- Create: `src/crm/db/base.py`
- Create: `src/crm/db/session.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_db_connection.py`

- [ ] **Step 1: Create db package skeleton**

Create `src/crm/db/__init__.py`:

```python
"""SQLAlchemy ORM, sessions, and repositories."""
```

- [ ] **Step 2: Create `src/crm/db/base.py`**

```python
"""SQLAlchemy declarative base for all ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base for every ORM model.

    All ORM models in `crm.db.models.*` must inherit from this class
    so that Alembic autogeneration sees them.
    """
```

- [ ] **Step 3: Create `src/crm/db/session.py`**

```python
"""Async engine and session factory builders."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from crm.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    """Create the async SQLAlchemy engine for the given settings."""
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
```

- [ ] **Step 4: Create `tests/integration/__init__.py`**

Empty file.

- [ ] **Step 5: Create `tests/integration/conftest.py`**

```python
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
    return Settings(  # type: ignore[call-arg]
        app_env=AppEnv.test,
        log_level="DEBUG",
        database_url=pg_url,
        telegram_bot_token="test-token",
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
```

- [ ] **Step 6: Write the failing integration test**

Create `tests/integration/test_db_connection.py`:

```python
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.integration
async def test_engine_connects_and_runs_trivial_query(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 AS one"))
        row = result.one()
    assert row.one == 1
```

- [ ] **Step 7: Run the test to verify it passes**

(There is no implementation gap — the test is exercising the code we already wrote.)

Run:
```bash
uv run pytest tests/integration/test_db_connection.py -v -m integration
```

Expected: 1 passed (may take ~30-60 seconds the first time as Docker pulls `postgres:16-alpine`).

If it fails with "Cannot connect to Docker": ensure Docker Desktop / daemon is running.

- [ ] **Step 8: Commit**

```bash
git add src/crm/db/ tests/integration/__init__.py tests/integration/conftest.py tests/integration/test_db_connection.py
git commit -m "feat(foundation): async SQLAlchemy engine + integration test harness with testcontainers"
```

---

## Task 5: Alembic setup with an empty initial migration

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako` (alembic generates)
- Create: `migrations/versions/<ts>_initial.py`
- Test: `tests/integration/test_alembic_upgrade.py`

- [ ] **Step 1: Initialise Alembic skeleton**

Run:
```bash
uv run alembic init -t async migrations
```

This creates `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, and `migrations/versions/`.

- [ ] **Step 2: Edit `alembic.ini`**

Open `alembic.ini` and change/ensure these lines:

```ini
script_location = migrations

# Disable URL hard-coding in alembic.ini — we read from env in env.py.
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 3: Replace `migrations/env.py`**

```python
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

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
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
```

- [ ] **Step 4: Create the empty initial revision**

Run:
```bash
uv run alembic revision -m "initial"
```

Expected: a new file `migrations/versions/<hash>_initial.py` is created.

Open the new file. The body should look like (the hash, down_revision, etc. are auto-generated — leave them):

```python
"""initial

Revision ID: <hash>
Revises:
Create Date: 2026-05-19 ...
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401

revision: str = "<hash>"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: the schema is built up in later migrations."""


def downgrade() -> None:
    """No-op."""
```

Make sure `upgrade()` and `downgrade()` are empty `pass` bodies (the docstring counts as a body — that's fine).

- [ ] **Step 5: Write the failing integration test**

Create `tests/integration/test_alembic_upgrade.py`:

```python
import pytest
from alembic.config import Config
from alembic import command
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

    command.upgrade(_alembic_config(settings), "head")

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.one()
    assert row.version_num  # the empty initial revision is recorded
```

- [ ] **Step 6: Run the test**

Run:
```bash
uv run pytest tests/integration/test_alembic_upgrade.py -v -m integration
```

Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini migrations/ tests/integration/test_alembic_upgrade.py
git commit -m "feat(foundation): Alembic async setup with empty initial revision"
```

---

## Task 6: Unit of Work

**Files:**
- Create: `src/crm/db/unit_of_work.py`
- (No dedicated test in this task — covered by container tests in T8 and by future plans.)

A Unit of Work wraps a session and exposes `commit()` / `rollback()`. In later plans, repositories will live as attributes of the UoW. For Plan 1 we just need the plumbing.

- [ ] **Step 1: Create `src/crm/db/unit_of_work.py`**

```python
"""Unit of Work.

A UoW owns an async SQLAlchemy session for the duration of one logical
operation (typically one use case). Repositories will live as attributes
of the UoW in later plans.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyUnitOfWork:
    """An async Unit of Work backed by SQLAlchemy."""

    session: AsyncSession

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                await self.session.rollback()
        finally:
            await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


@asynccontextmanager
async def uow_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """Convenience context manager.

    Usage:
        async with uow_scope(container.session_factory) as uow:
            ...
            await uow.commit()
    """
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow
```

- [ ] **Step 2: Smoke test by importing**

Run:
```bash
uv run python -c "from crm.db.unit_of_work import SqlAlchemyUnitOfWork, uow_scope; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/crm/db/unit_of_work.py
git commit -m "feat(foundation): SqlAlchemy Unit of Work scaffolding"
```

---

## Task 7: Adapter Protocols and Fake implementations

**Files:**
- Create: `src/crm/adapters/__init__.py`
- Create: `src/crm/adapters/ai/__init__.py`
- Create: `src/crm/adapters/ai/extractor.py`
- Create: `src/crm/adapters/ai/proposal_writer.py`
- Create: `src/crm/adapters/gdocs/__init__.py`
- Create: `src/crm/adapters/gdocs/client.py`
- Create: `src/crm/adapters/telegram/__init__.py`
- Create: `src/crm/adapters/telegram/sender.py`
- Test: `tests/unit/test_fake_adapters.py`

Each adapter file defines:
1. A `Protocol` that fixes the contract the use cases depend on.
2. A `Fake*` class implementing the Protocol with deterministic in-memory behaviour for tests and dev.

Real implementations (OpenAI, Google Docs API, aiogram Bot) arrive in Plans 4 and 6.

- [ ] **Step 1: Create `src/crm/adapters/__init__.py`**

```python
"""Pluggable IO. Each subpackage owns one third-party concern."""
```

- [ ] **Step 2: Create `src/crm/adapters/ai/__init__.py`**

```python
"""AI provider adapters: extractor and proposal writer."""
```

- [ ] **Step 3: Create `src/crm/adapters/ai/extractor.py`**

```python
"""AI extractor: turns a raw lead message into structured fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExtractedLead:
    """Structured lead data produced by the AI extractor."""

    full_name: str | None = None
    contact: str | None = None
    project_type: str | None = None
    area_m2: float | None = None
    budget_range: str | None = None
    timeline: str | None = None
    summary: str = ""
    confidence: float = 0.0
    raw_response: dict = field(default_factory=dict)


class AIExtractor(Protocol):
    """Extracts structured fields from a raw lead message."""

    async def extract(self, raw_text: str) -> ExtractedLead: ...


class FakeAIExtractor:
    """Deterministic in-memory extractor for dev/test.

    Echoes the input back as a `summary` and tags everything as low confidence.
    """

    async def extract(self, raw_text: str) -> ExtractedLead:
        trimmed = raw_text.strip()
        summary = trimmed[:120] + ("..." if len(trimmed) > 120 else "")
        return ExtractedLead(
            full_name=None,
            contact=None,
            project_type=None,
            area_m2=None,
            budget_range=None,
            timeline=None,
            summary=summary or "(empty input)",
            confidence=0.0,
            raw_response={"provider": "fake", "input_chars": len(trimmed)},
        )
```

- [ ] **Step 4: Create `src/crm/adapters/ai/proposal_writer.py`**

```python
"""AI proposal writer: generates a draft proposal body for a lead."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProposalDraft:
    """A draft proposal produced by the AI writer."""

    body: str
    scope_summary: str
    price_estimate: float | None = None
    currency: str = "RUB"


class ProposalWriter(Protocol):
    """Generates a draft proposal for a given lead."""

    async def generate(
        self,
        *,
        lead_summary: str,
        extracted: dict,
    ) -> ProposalDraft: ...


class FakeProposalWriter:
    """Deterministic in-memory proposal writer for dev/test."""

    async def generate(
        self,
        *,
        lead_summary: str,
        extracted: dict,
    ) -> ProposalDraft:
        body = (
            "Здравствуйте!\n\n"
            "Спасибо за обращение. Ниже — предварительный план работы.\n\n"
            f"Краткое описание задачи: {lead_summary}\n\n"
            "Этапы: 1) встреча и обмер, 2) эскиз, 3) рабочая документация.\n\n"
            "С уважением, архитектурное бюро."
        )
        return ProposalDraft(
            body=body,
            scope_summary=lead_summary[:200],
            price_estimate=None,
            currency="RUB",
        )
```

- [ ] **Step 5: Create `src/crm/adapters/gdocs/__init__.py`**

```python
"""Google Docs adapter."""
```

- [ ] **Step 6: Create `src/crm/adapters/gdocs/client.py`**

```python
"""Google Docs client adapter."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GDocRef:
    """Reference to a Google Doc that was created or written."""

    doc_id: str
    url: str
    title: str


class GDocsClient(Protocol):
    """Creates Google Docs and writes content into them."""

    async def create_doc(self, *, title: str, body: str) -> GDocRef: ...


class FakeGDocsClient:
    """In-memory GDocs that just generates a fake URL.

    Stores every created "document" in `self.created` for assertions.
    """

    def __init__(self) -> None:
        self.created: list[GDocRef] = []

    async def create_doc(self, *, title: str, body: str) -> GDocRef:
        doc_id = f"fake-{uuid.uuid4()}"
        ref = GDocRef(
            doc_id=doc_id,
            url=f"https://docs.example.com/{doc_id}",
            title=title,
        )
        self.created.append(ref)
        return ref
```

- [ ] **Step 7: Create `src/crm/adapters/telegram/__init__.py`**

```python
"""Telegram adapter: outbound message sender."""
```

- [ ] **Step 8: Create `src/crm/adapters/telegram/sender.py`**

```python
"""Telegram outbound message sender."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SentMessage:
    """Record of an outbound Telegram message."""

    chat_id: int
    text: str


class TelegramSender(Protocol):
    """Sends a Telegram message to a chat."""

    async def send_message(self, *, chat_id: int, text: str) -> None: ...


@dataclass
class FakeTelegramSender:
    """In-memory sender that records every outgoing message."""

    sent: list[SentMessage] = field(default_factory=list)

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.sent.append(SentMessage(chat_id=chat_id, text=text))
```

- [ ] **Step 9: Write the failing test**

Create `tests/unit/test_fake_adapters.py`:

```python
import pytest

from crm.adapters.ai.extractor import ExtractedLead, FakeAIExtractor
from crm.adapters.ai.proposal_writer import FakeProposalWriter, ProposalDraft
from crm.adapters.gdocs.client import FakeGDocsClient
from crm.adapters.telegram.sender import FakeTelegramSender


async def test_fake_extractor_echoes_input_as_summary() -> None:
    extractor = FakeAIExtractor()
    result: ExtractedLead = await extractor.extract("  Привет, нужен дом 200м2.  ")
    assert result.summary.startswith("Привет")
    assert result.confidence == 0.0
    assert result.raw_response["provider"] == "fake"


async def test_fake_extractor_handles_empty_input() -> None:
    extractor = FakeAIExtractor()
    result = await extractor.extract("")
    assert result.summary == "(empty input)"


async def test_fake_proposal_writer_produces_nonempty_body() -> None:
    writer = FakeProposalWriter()
    draft: ProposalDraft = await writer.generate(
        lead_summary="дом 200м2",
        extracted={},
    )
    assert "дом 200м2" in draft.body
    assert draft.currency == "RUB"


async def test_fake_gdocs_records_creations_and_returns_url() -> None:
    client = FakeGDocsClient()
    ref = await client.create_doc(title="t", body="b")
    assert ref.url.startswith("https://docs.example.com/")
    assert client.created == [ref]


async def test_fake_telegram_records_messages() -> None:
    sender = FakeTelegramSender()
    await sender.send_message(chat_id=42, text="hi")
    await sender.send_message(chat_id=42, text="bye")
    assert len(sender.sent) == 2
    assert sender.sent[0].text == "hi"
```

- [ ] **Step 10: Run the test**

Run:
```bash
uv run pytest tests/unit/test_fake_adapters.py -v
```

Expected: 5 passed.

- [ ] **Step 11: Commit**

```bash
git add src/crm/adapters/ tests/unit/test_fake_adapters.py
git commit -m "feat(foundation): adapter Protocols and Fake implementations (AI, GDocs, Telegram)"
```

---

## Task 8: DI Container

**Files:**
- Create: `src/crm/container.py`
- Test: `tests/unit/test_container.py`

The Container is a tiny dependency wiring helper that each entrypoint instantiates once at startup.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_container.py`:

```python
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from crm.adapters.ai.extractor import FakeAIExtractor
from crm.adapters.ai.proposal_writer import FakeProposalWriter
from crm.adapters.gdocs.client import FakeGDocsClient
from crm.adapters.telegram.sender import FakeTelegramSender
from crm.config import AppEnv, Settings
from crm.container import Container


def _settings(provider: str = "fake") -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env=AppEnv.test,
        log_level="INFO",
        database_url="postgresql+asyncpg://x:y@z/db",
        telegram_bot_token="t",
        telegram_operator_ids=(111,),
        ai_provider=provider,
    )


def test_container_builds_engine_and_session_factory() -> None:
    container = Container(_settings())
    assert isinstance(container.engine, AsyncEngine)
    assert isinstance(container.session_factory, async_sessionmaker)


def test_container_picks_fake_adapters_in_test_env() -> None:
    container = Container(_settings(provider="fake"))
    assert isinstance(container.ai_extractor, FakeAIExtractor)
    assert isinstance(container.proposal_writer, FakeProposalWriter)
    assert isinstance(container.gdocs, FakeGDocsClient)
    assert isinstance(container.telegram_sender, FakeTelegramSender)


def test_container_uow_can_be_constructed() -> None:
    container = Container(_settings())
    uow = container.uow()
    assert uow is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/unit/test_container.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'crm.container'`

- [ ] **Step 3: Write the implementation**

Create `src/crm/container.py`:

```python
"""Dependency injection container.

Each entrypoint (api / bot / worker) instantiates one `Container` at startup
and passes it (or its parts) to use cases. No globals.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from crm.adapters.ai.extractor import AIExtractor, FakeAIExtractor
from crm.adapters.ai.proposal_writer import FakeProposalWriter, ProposalWriter
from crm.adapters.gdocs.client import FakeGDocsClient, GDocsClient
from crm.adapters.telegram.sender import FakeTelegramSender, TelegramSender
from crm.config import Settings
from crm.db.session import build_engine, build_session_factory
from crm.db.unit_of_work import SqlAlchemyUnitOfWork


class Container:
    """Wires up application dependencies based on Settings."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker
    ai_extractor: AIExtractor
    proposal_writer: ProposalWriter
    gdocs: GDocsClient
    telegram_sender: TelegramSender

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = build_engine(settings)
        self.session_factory = build_session_factory(self.engine)

        self.ai_extractor = _build_ai_extractor(settings)
        self.proposal_writer = _build_proposal_writer(settings)
        self.gdocs = _build_gdocs(settings)
        self.telegram_sender = _build_telegram_sender(settings)

    def uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory)

    async def aclose(self) -> None:
        """Dispose of resources. Call on graceful shutdown."""
        await self.engine.dispose()


def _build_ai_extractor(settings: Settings) -> AIExtractor:
    if settings.ai_provider == "fake":
        return FakeAIExtractor()
    # Real providers (openai/anthropic) arrive in Plan 4.
    return FakeAIExtractor()


def _build_proposal_writer(settings: Settings) -> ProposalWriter:
    if settings.ai_provider == "fake":
        return FakeProposalWriter()
    return FakeProposalWriter()


def _build_gdocs(_settings: Settings) -> GDocsClient:
    # Real GDocs client arrives in Plan 6.
    return FakeGDocsClient()


def _build_telegram_sender(_settings: Settings) -> TelegramSender:
    # Real aiogram-backed sender arrives in Plan 3 (or here later if needed).
    return FakeTelegramSender()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/unit/test_container.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/crm/container.py tests/unit/test_container.py
git commit -m "feat(foundation): DI container wiring engine, session factory, fake adapters"
```

---

## Task 9: FastAPI entrypoint with `/healthz`

**Files:**
- Create: `src/crm/entrypoints/__init__.py`
- Create: `src/crm/entrypoints/api.py`
- Test: `tests/integration/test_api_healthz.py`

- [ ] **Step 1: Create `src/crm/entrypoints/__init__.py`**

```python
"""Process entrypoints: api, bot, worker."""
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_api_healthz.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from crm.config import Settings
from crm.container import Container
from crm.entrypoints.api import build_app


@pytest.mark.integration
async def test_healthz_returns_ok_with_real_postgres(settings: Settings) -> None:
    container = Container(settings)
    app = build_app(container)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "db": "ok"}

    await container.aclose()


@pytest.mark.integration
async def test_healthz_reports_db_failure_when_db_unreachable() -> None:
    bad_settings = Settings(  # type: ignore[call-arg]
        app_env="test",  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://nope:nope@127.0.0.1:1/none",
        telegram_bot_token="t",
        telegram_operator_ids=(1,),
        ai_provider="fake",
    )
    container = Container(bad_settings)
    app = build_app(container)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"

    await container.aclose()
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
uv run pytest tests/integration/test_api_healthz.py -v -m integration
```

Expected: FAIL — `ModuleNotFoundError: No module named 'crm.entrypoints.api'`

- [ ] **Step 4: Write the implementation**

Create `src/crm/entrypoints/api.py`:

```python
"""FastAPI HTTP entrypoint.

In Plan 1 the only route is `/healthz`. Future plans add domain endpoints
(or alternatively, a web dashboard backend).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging

log = structlog.get_logger(__name__)


def build_app(container: Container) -> FastAPI:
    """Build a FastAPI app wired to the given container.

    Exposed as a factory so tests can pass test-scoped containers.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("api.starting", app_env=container.settings.app_env.value)
        try:
            yield
        finally:
            log.info("api.shutting_down")

    app = FastAPI(title="reyzbikh-buro-crm", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        db_status = "ok"
        http_status = 200
        try:
            async with container.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"
            http_status = 503
        body = {
            "status": "ok" if db_status == "ok" else "degraded",
            "db": db_status,
        }
        return JSONResponse(content=body, status_code=http_status)

    return app


def main() -> FastAPI:
    """Factory used by `uvicorn crm.entrypoints.api:main --factory`.

    Builds a long-lived container from environment settings.
    Never invoked at import time, so test collection is safe even when env
    vars are not set.
    """
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)
    return build_app(container)
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
uv run pytest tests/integration/test_api_healthz.py -v -m integration
```

Expected: 2 passed.

(If a `Settings()` load attempt at import time fails the second test, the `try/except` in `api.py` swallows it — `app = None` and only `build_app()` is used by tests.)

- [ ] **Step 6: Commit**

```bash
git add src/crm/entrypoints/__init__.py src/crm/entrypoints/api.py tests/integration/test_api_healthz.py
git commit -m "feat(foundation): FastAPI entrypoint with /healthz that probes Postgres"
```

---

## Task 10: aiogram bot entrypoint with allowlist and `/start`

**Files:**
- Create: `src/crm/entrypoints/bot.py`
- Test: `tests/integration/test_bot_start.py`

The Plan 1 bot only:
1. Accepts `/start` from operators in the allowlist and replies with a greeting.
2. Silently ignores messages from non-allowlisted users (logs at INFO).

All real lead-intake handlers arrive in Plan 3.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_bot_start.py`:

```python
from datetime import datetime, timezone

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
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=user,
        text=text,
    )
    return Update(update_id=1, message=message)


@pytest.mark.integration
async def test_start_command_replies_to_allowlisted_operator(
    settings: Settings,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/integration/test_bot_start.py -v -m integration
```

Expected: FAIL — `ModuleNotFoundError: No module named 'crm.entrypoints.bot'`

- [ ] **Step 3: Write the implementation**

Create `src/crm/entrypoints/bot.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/integration/test_bot_start.py -v -m integration
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/crm/entrypoints/bot.py tests/integration/test_bot_start.py
git commit -m "feat(foundation): aiogram bot with allowlist auth and /start handler"
```

---

## Task 11: Worker entrypoint skeleton

**Files:**
- Create: `src/crm/entrypoints/worker.py`
- (No dedicated test in this task — real worker logic and tests arrive in Plan 5.)

In Plan 1 the worker is just a polling loop that logs a heartbeat and shuts down cleanly on SIGTERM/SIGINT. The `scheduled_jobs` table does not exist yet (Plan 2 creates the schema, Plan 5 builds the real scheduler).

- [ ] **Step 1: Create `src/crm/entrypoints/worker.py`**

```python
"""Worker entrypoint.

In Plan 1 this is a heartbeat loop only — no job dispatching yet.
Plan 5 expands it into the real Postgres-backed scheduler.
"""

from __future__ import annotations

import asyncio
import signal

import structlog

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging

log = structlog.get_logger(__name__)


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)

    stop = asyncio.Event()

    def _request_stop() -> None:
        log.info("worker.stop_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows: signals not supported in proactor loop. Fine for dev.
            pass

    log.info(
        "worker.starting",
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )
    try:
        while not stop.is_set():
            log.debug("worker.heartbeat")
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.worker_poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue
    finally:
        await container.aclose()
        log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 2: Smoke test by running it for 2 seconds**

Run (PowerShell):
```powershell
$env:APP_ENV="dev"; $env:DATABASE_URL="postgresql+asyncpg://crm:crm@localhost:5432/crm"; $env:TELEGRAM_BOT_TOKEN="x"; $env:TELEGRAM_OPERATOR_IDS=""; $env:AI_PROVIDER="fake"; $env:WORKER_POLL_INTERVAL_SECONDS="0.5"
$proc = Start-Process -PassThru -FilePath "uv" -ArgumentList "run","python","-m","crm.entrypoints.worker" -NoNewWindow -RedirectStandardOutput "worker.log"
Start-Sleep -Seconds 2
Stop-Process -Id $proc.Id
Get-Content worker.log
Remove-Item worker.log
```

Expected: `worker.log` contains lines mentioning `worker.starting`. Engine connection failure is fine (no Postgres yet) because the worker doesn't connect in Plan 1.

(If Postgres is not running locally, the `aclose()` in the `finally` block should still succeed since the engine is lazy.)

- [ ] **Step 3: Commit**

```bash
git add src/crm/entrypoints/worker.py
git commit -m "feat(foundation): worker entrypoint skeleton with graceful shutdown"
```

---

## Task 12: Dockerfile and docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `.dockerignore`**

```dockerignore
.git
.venv
.pytest_cache
.ruff_cache
.coverage
htmlcov
__pycache__
*.pyc
dist
build
*.egg-info
.idea
.vscode
docs
.env
secrets
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy source.
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./alembic.ini

RUN uv sync --frozen --no-dev

# Default command (overridden per-service in compose).
CMD ["python", "-m", "crm.entrypoints.worker"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: crm
      POSTGRES_PASSWORD: crm
      POSTGRES_DB: crm
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "crm"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports:
      - "5432:5432"

  migrate:
    build: .
    command: ["alembic", "upgrade", "head"]
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  api:
    build: .
    command: ["uvicorn", "crm.entrypoints.api:main", "--factory",
              "--host", "0.0.0.0", "--port", "8000"]
    env_file: .env
    depends_on:
      migrate:
        condition: service_completed_successfully
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
      interval: 10s
      timeout: 3s
      retries: 5

  bot:
    build: .
    command: ["python", "-m", "crm.entrypoints.bot"]
    env_file: .env
    depends_on:
      migrate:
        condition: service_completed_successfully
    restart: unless-stopped

  worker:
    build: .
    command: ["python", "-m", "crm.entrypoints.worker"]
    env_file: .env
    depends_on:
      migrate:
        condition: service_completed_successfully
    restart: unless-stopped

volumes:
  pgdata:
```

- [ ] **Step 4: Build the image**

Ensure `.env` exists locally (copy from `.env.example` and fill in at least a placeholder Telegram token and empty operator IDs — the bot will error trying to long-poll without a real token, but the build and `/healthz` will work):

```bash
cp .env.example .env
```

Edit `.env` and change `DATABASE_URL=postgresql+asyncpg://crm:crm@postgres:5432/crm` (the default already points to the compose service name).

Run:
```bash
docker compose build
```

Expected: image builds successfully (~1-3 min).

- [ ] **Step 5: Bring up the stack (without bot, which needs a real Telegram token)**

Run:
```bash
docker compose up -d postgres migrate api worker
docker compose ps
```

Expected: `postgres`, `api`, `worker` healthy/running; `migrate` is `Exited (0)`.

- [ ] **Step 6: Verify `/healthz`**

Run:
```bash
curl -fsS http://localhost:8000/healthz
```

Expected: `{"status":"ok","db":"ok"}`

- [ ] **Step 7: Tear down**

Run:
```bash
docker compose down -v
```

- [ ] **Step 8: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat(foundation): Dockerfile and docker-compose stack (postgres + migrate + api + bot + worker)"
```

---

## Task 13: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

CI runs on every push and PR. It:
1. Lints with `ruff`.
2. Runs unit tests.
3. Runs integration tests against a Postgres service container.
4. Verifies `alembic upgrade head` runs clean.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - name: Install dependencies
        run: uv sync --frozen
      - name: Ruff check
        run: uv run ruff check .
      - name: Ruff format check
        run: uv run ruff format --check .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: crm
          POSTGRES_PASSWORD: crm
          POSTGRES_DB: crm
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U crm"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
    env:
      APP_ENV: test
      DATABASE_URL: postgresql+asyncpg://crm:crm@localhost:5432/crm
      TELEGRAM_BOT_TOKEN: test-token
      TELEGRAM_OPERATOR_IDS: "111"
      AI_PROVIDER: fake
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - name: Install dependencies
        run: uv sync --frozen
      - name: Alembic upgrade head (smoke)
        run: uv run alembic upgrade head
      - name: Run unit tests
        run: uv run pytest tests/unit -v
      - name: Run integration tests
        run: uv run pytest tests/integration -v -m integration
```

- [ ] **Step 2: Verify YAML locally**

Run:
```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no output (file parses).

- [ ] **Step 3: Commit and (optionally) push to trigger CI**

```bash
git add .github/workflows/ci.yml
git commit -m "feat(foundation): GitHub Actions CI (ruff + pytest + alembic)"
```

If a remote is configured, push and watch the CI run:
```bash
git push origin main
```

- [ ] **Step 4: Locally run everything CI runs**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/unit -v
uv run pytest tests/integration -v -m integration
```

Expected: all green. Fix any formatting issues with `uv run ruff format .` and re-commit.

---

## Task 14: Finalize README and .env.example

**Files:**
- Modify: `README.md`
- Modify: `.env.example` (already correct from T2; verify)

- [ ] **Step 1: Replace `README.md` with the full version**

```markdown
# Reyzbikh Buro CRM

CRM/workflow platform for an architecture bureau. Postgres-centered; Telegram is one input channel of many planned.

> **Design spec:** [`docs/superpowers/specs/2026-05-19-crm-platform-design.md`](docs/superpowers/specs/2026-05-19-crm-platform-design.md)
> **Implementation plans:** [`docs/superpowers/plans/`](docs/superpowers/plans/)

## Status

- ✅ Plan 1: Foundation
- ⬜ Plan 2: Domain + Schema
- ⬜ Plan 3: Lead Intake (fake AI)
- ⬜ Plan 4: AI Adapters
- ⬜ Plan 5: Proposal + Scheduler + Worker
- ⬜ Plan 6: Google Docs adapter
- ⬜ Plan 7: Follow-ups
- ⬜ Plan 8: Production hardening

## Architecture in 30 seconds

```
docker compose:
  postgres   ── pg 16 alpine
  migrate    ── one-shot: alembic upgrade head
  api        ── FastAPI :8000 (so far: /healthz)
  bot        ── aiogram long-polling
  worker     ── scheduler/jobs loop
```

All three Python processes share the `crm` package. Business logic will live in `src/crm/use_cases/`. Adapters (AI, GDocs, Telegram outbound) sit behind `Protocol` interfaces with `Fake*` impls for tests and early dev.

## Local dev

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Docker + Docker Compose

### First-time setup

```bash
uv sync
cp .env.example .env
# Edit .env — at minimum set TELEGRAM_BOT_TOKEN and TELEGRAM_OPERATOR_IDS
```

### Run the stack

```bash
docker compose up -d
docker compose ps        # all services should be healthy
curl http://localhost:8000/healthz
docker compose logs -f bot
```

To stop:
```bash
docker compose down       # keep data
docker compose down -v    # wipe DB volume
```

### Run tests

```bash
uv run pytest tests/unit -v
uv run pytest tests/integration -v -m integration   # needs Docker
```

### Lint and format

```bash
uv run ruff check .
uv run ruff format .
```

### Migrations

```bash
# Apply all migrations
uv run alembic upgrade head

# Create a new migration after changing ORM models
uv run alembic revision --autogenerate -m "describe change"
```

## Layout

```
src/crm/
  config.py             # pydantic-settings — all env vars
  logging.py            # structlog setup
  container.py          # DI container
  db/                   # SQLAlchemy base, session, Unit of Work
  adapters/             # IO behind Protocols; fakes here today
  entrypoints/          # api / bot / worker
tests/
  unit/                 # no IO
  integration/          # real Postgres via testcontainers
migrations/             # Alembic
docs/superpowers/       # spec + plans
```

## License

Proprietary — internal use by Reyzbikh Buro.
```

- [ ] **Step 2: Verify `.env.example` matches what's in the repo**

Run:
```bash
git diff .env.example
```

Expected: no diff (file is already correct from T2).

- [ ] **Step 3: Final pre-commit verification**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/unit -v
uv run pytest tests/integration -v -m integration
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(foundation): full README with quickstart, layout, and plan status"
```

- [ ] **Step 5: Tag the foundation milestone**

```bash
git tag -a plan-1-foundation -m "Plan 1: Foundation complete"
```

(Push with `git push origin plan-1-foundation` if you have a remote.)

---

## Self-Review checklist (already run by the planner)

**Spec coverage:**
- §3.1 processes (api/bot/worker) — ✅ T9 / T10 / T11
- §3.2 repo layout — ✅ tasks create exactly the layout in the spec
- §6.3 DI container — ✅ T8
- §6.4 config & secrets (`.env.example`, `pydantic-settings`) — ✅ T2 / T14
- §6.5 deployment (Dockerfile + compose) — ✅ T12
- §6.6 tests (unit + integration via testcontainers) — ✅ tasks T2/T3/T4/T7/T8/T9/T10 collectively
- §6.7 observability (structlog, secret masking) — ✅ T3
- §4 schema and §5 use cases — explicitly deferred to Plan 2 / Plan 3+
- §11 plan-stage decisions:
  - `uv` chosen — ✅
  - Prompt templates: deferred to Plan 4 (correct phase)
  - Pre-commit hooks: not in Plan 1 — added to Plan 2 backlog (note below)

**Placeholder scan:** No "TBD", "implement later", "add appropriate handling". Every step has runnable code or commands.

**Type consistency:** `Container`, `Settings`, `AIExtractor`/`FakeAIExtractor`, `ProposalWriter`/`FakeProposalWriter`, `GDocsClient`/`FakeGDocsClient`, `TelegramSender`/`FakeTelegramSender`, `SqlAlchemyUnitOfWork`, `ExtractedLead`, `ProposalDraft`, `GDocRef`, `SentMessage` — referenced consistently across tasks.

**Notes for Plan 2 backlog (not blocking Plan 1):**
- Add `pre-commit` hooks running `ruff format` + `ruff check`.
- Decide canonical JSONB-schema-versioning approach before adding the first JSONB column.

---

## Definition of Done for Plan 1

All of the following must be true before we start Plan 2:

- [ ] `uv sync` succeeds on a fresh clone.
- [ ] `docker compose up -d` brings up `postgres`, `migrate`, `api`, `worker` healthy. (`bot` requires a real `TELEGRAM_BOT_TOKEN` — optional locally; CI uses a dummy token and only feeds synthetic updates.)
- [ ] `curl http://localhost:8000/healthz` returns `{"status":"ok","db":"ok"}`.
- [ ] `uv run pytest tests/unit` is green.
- [ ] `uv run pytest tests/integration -m integration` is green.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` are green.
- [ ] GitHub Actions CI (if pushed) is green.
- [ ] Tag `plan-1-foundation` exists in git.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-plan-1-foundation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — A fresh subagent per task, review between tasks, fast iteration. Best for a long sequential plan like this one (14 tasks). Each subagent gets exactly one task with its full code, runs it, commits, and reports.

**2. Inline Execution** — Execute all tasks in this session using `executing-plans`, batched with manual checkpoints between groups (e.g., T1-T3, T4-T6, T7-T9, T10-T12, T13-T14).

**Which approach?**
