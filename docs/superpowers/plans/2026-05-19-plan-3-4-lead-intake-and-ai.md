# Plan 3+4: Lead Intake + AI Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the first interactive use cases (`intake_lead`, `qualify_lead`), expose them through the Telegram bot, and swap the fake AI extractor/proposal-writer for real OpenAI implementations driven by Jinja-templated prompts.

**Architecture:** Use cases live in `src/crm/use_cases/<name>.py`, take a UoW + adapters explicitly (no global state), open their own transaction, call AI **outside** the transaction (spec §6.3), then commit in a second transaction. Bot handlers in `src/crm/entrypoints/bot.py` translate Telegram events into use-case calls — no business logic in handlers. Real AI adapters in `src/crm/adapters/ai/openai_*.py` use `openai>=1.x` with `response_format={"type": "json_object"}` + a Jinja-rendered system prompt.

**Tech Stack:** SQLAlchemy 2.0 (already wired), aiogram 3 (already wired), `openai>=1.50`, `jinja2`, `pytest-asyncio`.

---

## Branch

Branch from the merged Plan 2 work:

```powershell
cd C:\Repos\reyzbikh_buro_crm
git checkout main
git pull --ff-only origin main
git checkout -b plan-3-4-lead-intake-ai
```

Two tags get created at the end of the plan: `plan-3-lead-intake` (after T5) and `plan-4-ai-adapters` (after T10).

---

## Prerequisites

Already there from Plan 1+2:
- `crm.adapters.ai.extractor` has `AIExtractor` Protocol + `ExtractedLead` dataclass + `FakeAIExtractor`.
- `crm.adapters.ai.proposal_writer` has `ProposalWriter` Protocol + `ProposalDraft` dataclass + `FakeProposalWriter`.
- `Container` builds fakes when `settings.ai_provider == "fake"` (today: always fake).
- All 10 ORM models + repos + UoW.
- 39 tests passing.

Sanity check before starting:

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format --check .
docker info
```

---

## File Structure

### Created in this plan

```
src/crm/
  use_cases/
    __init__.py
    events.py                       # record_event helper
    intake_lead.py                  # intake_lead(...)
    qualify_lead.py                 # qualify_lead(...)
  adapters/ai/
    openai_extractor.py             # OpenAIExtractor
    openai_proposal_writer.py       # OpenAIProposalWriter
  prompts/
    __init__.py                     # render(...) helper
    extract_lead.j2
    generate_proposal.j2

tests/
  unit/
    test_record_event.py
    test_intake_lead_unit.py        # use case with fake adapters + in-memory session
    test_qualify_lead_unit.py
    test_openai_extractor.py        # mocked AsyncOpenAI
    test_openai_proposal_writer.py
    test_prompts.py                 # render() smoke
  integration/
    test_intake_lead.py             # real Postgres via testcontainers
    test_qualify_lead.py
    test_bot_handlers.py            # bot router with stub bot/dispatcher
```

### Modified in this plan

```
pyproject.toml                       # add openai, jinja2 (+ pytest-mock optional)
src/crm/container.py                 # build_ai_extractor / build_proposal_writer switching
src/crm/entrypoints/bot.py           # text + callback handlers
src/crm/adapters/ai/extractor.py     # NO refactor — already correct from Plan 1
README.md                            # bump status
```

---

## Conventions

- `uv` lives at `& "$env:USERPROFILE\.local\bin\uv.exe"`.
- All datetimes are timezone-aware (`datetime.now(UTC)`).
- Use cases never commit inside loops; they open a UoW, do the work, `await uow.commit()` once.
- Bot handlers never touch the DB directly — they only call use cases.
- `events.payload` is `dict[str, Any]`; payload schema lives in the spec, not validated in code (per §4.4 Decision 6).
- Tests use `pytest-asyncio` (already in dev deps).

---

## Task 1: `record_event` helper

**Files:**
- Create: `src/crm/use_cases/__init__.py`
- Create: `src/crm/use_cases/events.py`
- Test: `tests/unit/test_record_event.py`

The helper writes one `Event` row inside the caller's UoW session. It does NOT commit — the caller controls the transaction boundary.

- [ ] **Step 1: Create `src/crm/use_cases/__init__.py`**

```python
"""Use cases — the single home of business logic.

Each module exposes one async function with explicit dependencies (UoW +
adapters). Bot handlers, API endpoints, and the worker all call into here.
"""
```

- [ ] **Step 2: Write the failing unit test**

Create `tests/unit/test_record_event.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.use_cases.events import record_event


@pytest.mark.asyncio
async def test_record_event_adds_event_to_session() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    uow = MagicMock()
    uow.session = session

    await record_event(
        uow,
        event_type="lead.created",
        aggregate_type="lead",
        aggregate_id=42,
        payload={"channel": "telegram"},
        actor_user_id=7,
    )

    assert session.add.call_count == 1
    added = session.add.call_args.args[0]
    assert added.event_type == "lead.created"
    assert added.aggregate_type == "lead"
    assert added.aggregate_id == 42
    assert added.payload == {"channel": "telegram"}
    assert added.actor_user_id == 7
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_event_defaults_payload_and_actor() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    uow = MagicMock()
    uow.session = session

    await record_event(
        uow,
        event_type="lead.archived",
        aggregate_type="lead",
        aggregate_id=99,
    )

    added = session.add.call_args.args[0]
    assert added.payload == {}
    assert added.actor_user_id is None


@pytest.mark.asyncio
async def test_record_event_does_not_commit() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    uow = MagicMock()
    uow.session = session

    await record_event(
        uow,
        event_type="lead.created",
        aggregate_type="lead",
        aggregate_id=1,
    )

    session.commit.assert_not_called()
```

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_record_event.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crm.use_cases.events'`.

- [ ] **Step 3: Create `src/crm/use_cases/events.py`**

```python
"""record_event helper — single entry point for writing to the events log."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from crm.db.models.event import Event

if TYPE_CHECKING:
    from crm.db.unit_of_work import SqlAlchemyUnitOfWork


async def record_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int | None,
    payload: dict[str, Any] | None = None,
    actor_user_id: int | None = None,
) -> Event:
    """Append one row to the events table inside the caller's UoW.

    Does NOT commit. Use cases own the transaction boundary; this helper
    only stages the insert and flushes so `event.id` is populated.

    Args:
        uow: An open SqlAlchemyUnitOfWork.
        event_type: Dotted event name, e.g. ``"lead.created"``.
        aggregate_type: Domain aggregate the event belongs to (``"lead"``,
            ``"proposal"``, ``"project"``, ...). Used for indexed lookups.
        aggregate_id: Primary key of the aggregate, or ``None`` for events
            not tied to a single row (rare).
        payload: Free-form JSONB body. Defaults to ``{}``.
        actor_user_id: The User who triggered the change, or ``None`` for
            system-driven events (worker tick, AI follow-up).

    Returns:
        The persisted ``Event`` instance with ``id`` populated.
    """
    event = Event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload if payload is not None else {},
        actor_user_id=actor_user_id,
    )
    uow.session.add(event)
    await uow.session.flush()
    return event
```

- [ ] **Step 4: Run unit tests — expect PASS**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_record_event.py -v
```

Expected: **3 passed**.

- [ ] **Step 5: Full suite (no regressions)**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 42 passed (39 + 3).

- [ ] **Step 6: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/use_cases/__init__.py src/crm/use_cases/events.py tests/unit/test_record_event.py
git commit -m "feat(use_cases): record_event helper writes audit events inside UoW"
```

---

## Task 2: `intake_lead` use case

**Files:**
- Create: `src/crm/use_cases/intake_lead.py`
- Test: `tests/unit/test_intake_lead_unit.py`
- Test: `tests/integration/test_intake_lead.py`

**Contract** (per spec §5.1 + §5.4):

```python
async def intake_lead(
    container: Container,
    *,
    raw_text: str,
    channel: ChannelKind,
    channel_message_id: str | None,
    operator_user_id: int | None,
) -> Lead: ...
```

**Flow:**
1. **Txn 1**: Insert `Lead(status=new, raw_text=..., channel=..., channel_message_id=..., assigned_to_user_id=operator_user_id)`. Record event `lead.created`. Commit. Return lead.id.
2. **Outside txn**: `extracted = await container.ai_extractor.extract(raw_text)`. If raises, fall to step 3b.
3a. **Txn 2 (success)**: Re-load Lead, set `extracted_data=extracted.raw_response`, `summary=extracted.summary`, `status=qualifying`. Record event `lead.extracted` with payload `{"confidence": ..., "summary": ...}`. Commit.
3b. **Txn 2 (failure)**: Re-load Lead, leave `status=new`, set `extracted_data={"_extraction_failed": True, "error": <str(exc)>}`. Record event `lead.extraction_failed` with payload `{"error": ...}`. Commit.
4. Return the Lead (final state).

- [ ] **Step 1: Write integration test (TDD)**

Create `tests/integration/test_intake_lead.py`:

```python
"""Integration tests for intake_lead use case (real Postgres)."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import ChannelKind, LeadStatus
from crm.use_cases.intake_lead import intake_lead


def _alembic_config(settings: Settings) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def _migrate(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.integration
async def test_intake_lead_happy_path_creates_lead_and_extracts(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    lead = await intake_lead(
        container,
        raw_text="Иван, дом 200 м2, бюджет 3 млн, к маю",
        channel=ChannelKind.telegram,
        channel_message_id="tg:42",
        operator_user_id=None,
    )

    assert lead.id is not None
    assert lead.status == LeadStatus.qualifying
    assert lead.raw_text.startswith("Иван")
    assert lead.summary is not None
    assert "_extraction_failed" not in lead.extracted_data

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("lead", lead.id)
    types = [e.event_type for e in events]
    assert "lead.created" in types
    assert "lead.extracted" in types
    assert "lead.extraction_failed" not in types

    await container.aclose()


@pytest.mark.integration
async def test_intake_lead_handles_ai_failure(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crm.adapters.ai.extractor import AIExtractor, ExtractedLead

    class BrokenExtractor:
        async def extract(self, raw_text: str) -> ExtractedLead:
            raise RuntimeError("upstream AI is down")

    await _migrate(settings, monkeypatch)
    container = Container(settings)
    container.ai_extractor = BrokenExtractor()  # type: ignore[assignment]

    lead = await intake_lead(
        container,
        raw_text="quick lead",
        channel=ChannelKind.telegram,
        channel_message_id="tg:7",
        operator_user_id=None,
    )

    assert lead.status == LeadStatus.new
    assert lead.extracted_data.get("_extraction_failed") is True
    assert "upstream AI is down" in lead.extracted_data.get("error", "")

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("lead", lead.id)
    types = [e.event_type for e in events]
    assert "lead.created" in types
    assert "lead.extraction_failed" in types
    assert "lead.extracted" not in types

    await container.aclose()


@pytest.mark.integration
async def test_intake_lead_records_actor_user_id_on_events(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crm.db.models.enums import UserRole
    from crm.db.models.user import User

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        operator = await uow.users.add(
            User(telegram_id=1001, display_name="Op", role=UserRole.owner)
        )
        await uow.commit()
        operator_id = operator.id

    lead = await intake_lead(
        container,
        raw_text="hi",
        channel=ChannelKind.telegram,
        channel_message_id=None,
        operator_user_id=operator_id,
    )

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("lead", lead.id)
    actors = {e.actor_user_id for e in events}
    assert actors == {operator_id}
    assert lead.assigned_to_user_id == operator_id

    await container.aclose()
```

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_intake_lead.py -v -m integration`
Expected: FAIL with `ModuleNotFoundError: No module named 'crm.use_cases.intake_lead'`.

- [ ] **Step 2: Create `src/crm/use_cases/intake_lead.py`**

```python
"""intake_lead use case — first step of the lead workflow.

Spec §5.1, steps 1-5. Two transactions:

  TX1: INSERT Lead (status=new) + record event lead.created → commit.
  --- AI extractor call happens OUTSIDE any DB transaction ---
  TX2: UPDATE Lead with extracted data + status=qualifying + event
       lead.extracted → commit. If the AI call failed, instead record
       lead.extraction_failed and leave status=new.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import ChannelKind, LeadStatus
from crm.db.models.lead import Lead
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)


async def intake_lead(
    container: Container,
    *,
    raw_text: str,
    channel: ChannelKind,
    channel_message_id: str | None,
    operator_user_id: int | None,
) -> Lead:
    """Ingest a raw lead message and run AI extraction.

    Returns the Lead with its final post-extraction state. The Lead is
    always persisted even if extraction fails — operators can re-run
    extraction manually later.
    """
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=channel,
                channel_message_id=channel_message_id,
                raw_text=raw_text,
                status=LeadStatus.new,
                assigned_to_user_id=operator_user_id,
            )
        )
        await record_event(
            uow,
            event_type="lead.created",
            aggregate_type="lead",
            aggregate_id=lead.id,
            payload={
                "channel": channel.value,
                "channel_message_id": channel_message_id,
                "raw_text_chars": len(raw_text),
            },
            actor_user_id=operator_user_id,
        )
        await uow.commit()
        lead_id = lead.id

    log.info("intake_lead.created", lead_id=lead_id)

    try:
        extracted = await container.ai_extractor.extract(raw_text)
        extraction_error: Exception | None = None
    except Exception as exc:  # noqa: BLE001  upstream AI failures are arbitrary
        log.warning(
            "intake_lead.extraction_failed",
            lead_id=lead_id,
            error=str(exc),
        )
        extracted = None
        extraction_error = exc

    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        assert lead is not None  # we just inserted it

        if extracted is not None:
            lead.summary = extracted.summary
            lead.extracted_data = dict(extracted.raw_response)
            lead.status = LeadStatus.qualifying
            await record_event(
                uow,
                event_type="lead.extracted",
                aggregate_type="lead",
                aggregate_id=lead_id,
                payload={
                    "summary": extracted.summary,
                    "confidence": extracted.confidence,
                },
                actor_user_id=operator_user_id,
            )
        else:
            assert extraction_error is not None
            lead.extracted_data = {
                "_extraction_failed": True,
                "error": str(extraction_error),
            }
            await record_event(
                uow,
                event_type="lead.extraction_failed",
                aggregate_type="lead",
                aggregate_id=lead_id,
                payload={"error": str(extraction_error)},
                actor_user_id=operator_user_id,
            )

        await uow.commit()
        result = lead

    log.info(
        "intake_lead.finished",
        lead_id=lead_id,
        status=result.status,
        ai_ok=extraction_error is None,
    )
    return result
```

- [ ] **Step 3: Lightweight unit test (no DB)**

Create `tests/unit/test_intake_lead_unit.py`:

```python
"""Unit tests for intake_lead — verifies the use case wires its parts
together without booting a real database."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.extractor import ExtractedLead
from crm.db.models.enums import ChannelKind, LeadStatus
from crm.use_cases.intake_lead import intake_lead


def _stub_lead(lead_id: int = 1) -> MagicMock:
    lead = MagicMock()
    lead.id = lead_id
    lead.status = LeadStatus.new
    lead.extracted_data = {}
    lead.summary = None
    return lead


@pytest.mark.asyncio
async def test_intake_lead_calls_ai_outside_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    lead = _stub_lead()

    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.leads = MagicMock()
    uow.leads.add = AsyncMock(return_value=lead)
    uow.leads.get = AsyncMock(return_value=lead)

    container = MagicMock()
    container.uow = MagicMock(return_value=uow)
    container.ai_extractor = MagicMock()
    container.ai_extractor.extract = AsyncMock(
        return_value=ExtractedLead(summary="ok", confidence=0.8, raw_response={"k": "v"})
    )

    result = await intake_lead(
        container,
        raw_text="hello",
        channel=ChannelKind.telegram,
        channel_message_id="tg:1",
        operator_user_id=42,
    )

    assert result.status == LeadStatus.qualifying
    assert result.summary == "ok"
    assert result.extracted_data == {"k": "v"}
    container.ai_extractor.extract.assert_awaited_once_with("hello")
    assert uow.commit.await_count == 2
```

- [ ] **Step 4: Run tests**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_intake_lead_unit.py tests/integration/test_intake_lead.py -v
```

Expected: **1 unit + 3 integration = 4 passed**.

- [ ] **Step 5: Full suite**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 46 passed (42 + 4).

- [ ] **Step 6: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/use_cases/intake_lead.py tests/unit/test_intake_lead_unit.py tests/integration/test_intake_lead.py
git commit -m "feat(use_cases): intake_lead — create Lead, run AI extraction, emit events"
```

---

## Task 3: `qualify_lead` use case

**Files:**
- Create: `src/crm/use_cases/qualify_lead.py`
- Test: `tests/unit/test_qualify_lead_unit.py`
- Test: `tests/integration/test_qualify_lead.py`

**Contract:**

```python
async def qualify_lead(
    container: Container,
    *,
    lead_id: int,
    operator_user_id: int | None,
) -> Lead: ...
```

**Flow:**
1. Open UoW.
2. Load lead by id. If missing → `LeadNotFoundError`. If `status not in {qualifying, new}` → `LeadCannotQualifyError`.
3. If `lead.client_id is None` and `extracted_data` has `full_name`: create a `Client`, set `lead.client_id`.
4. Set `lead.status = qualified`.
5. Record event `lead.qualified` with payload `{"created_client_id": <id or null>}`.
6. Commit. Return lead.

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_qualify_lead.py`:

```python
"""Integration tests for qualify_lead."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import ChannelKind, LeadStatus
from crm.db.models.lead import Lead
from crm.use_cases.qualify_lead import (
    LeadCannotQualifyError,
    LeadNotFoundError,
    qualify_lead,
)


def _alembic_config(settings: Settings) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def _migrate(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def _add_lead(
    container: Container,
    *,
    status: LeadStatus,
    extracted_data: dict | None = None,
) -> int:
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="raw",
                status=status,
                extracted_data=extracted_data or {},
            )
        )
        await uow.commit()
        return lead.id


@pytest.mark.integration
async def test_qualify_lead_promotes_to_qualified(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    lead_id = await _add_lead(
        container,
        status=LeadStatus.qualifying,
        extracted_data={"full_name": "Иван", "contact": "+7900xxx"},
    )

    lead = await qualify_lead(container, lead_id=lead_id, operator_user_id=None)

    assert lead.status == LeadStatus.qualified
    assert lead.client_id is not None

    async with container.uow() as uow:
        client = await uow.clients.get(lead.client_id)
    assert client is not None
    assert client.full_name == "Иван"
    assert client.phone == "+7900xxx"

    await container.aclose()


@pytest.mark.integration
async def test_qualify_lead_without_extracted_name_skips_client_creation(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    lead_id = await _add_lead(
        container,
        status=LeadStatus.qualifying,
        extracted_data={"summary": "no name"},
    )

    lead = await qualify_lead(container, lead_id=lead_id, operator_user_id=None)

    assert lead.status == LeadStatus.qualified
    assert lead.client_id is None

    await container.aclose()


@pytest.mark.integration
async def test_qualify_lead_records_event(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    lead_id = await _add_lead(
        container,
        status=LeadStatus.qualifying,
        extracted_data={"full_name": "X"},
    )

    await qualify_lead(container, lead_id=lead_id, operator_user_id=None)

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("lead", lead_id)
    types = [e.event_type for e in events]
    assert "lead.qualified" in types

    await container.aclose()


@pytest.mark.integration
async def test_qualify_lead_raises_when_missing(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    with pytest.raises(LeadNotFoundError):
        await qualify_lead(container, lead_id=999_999, operator_user_id=None)

    await container.aclose()


@pytest.mark.integration
async def test_qualify_lead_rejects_terminal_states(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    lead_id = await _add_lead(container, status=LeadStatus.archived)

    with pytest.raises(LeadCannotQualifyError):
        await qualify_lead(container, lead_id=lead_id, operator_user_id=None)

    await container.aclose()
```

Run: expects `ModuleNotFoundError: No module named 'crm.use_cases.qualify_lead'`.

- [ ] **Step 2: Create `src/crm/use_cases/qualify_lead.py`**

```python
"""qualify_lead use case.

Spec §5.1 step 7. Promotes a Lead from `qualifying`/`new` to `qualified`
and — if the extracted data has enough info — creates a Client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from crm.db.models.client import Client
from crm.db.models.enums import ClientSource, LeadStatus
from crm.db.models.lead import Lead
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)


class LeadNotFoundError(LookupError):
    """The requested lead does not exist."""


class LeadCannotQualifyError(ValueError):
    """The lead is in a status from which it cannot be qualified."""


_QUALIFIABLE_FROM: frozenset[LeadStatus] = frozenset(
    {LeadStatus.new, LeadStatus.qualifying}
)


async def qualify_lead(
    container: Container,
    *,
    lead_id: int,
    operator_user_id: int | None,
) -> Lead:
    """Move a Lead to `qualified` and optionally materialise a Client.

    Raises:
        LeadNotFoundError: no Lead with this id.
        LeadCannotQualifyError: Lead is in a status that doesn't allow
            qualification (e.g. already `accepted`, `declined`, or
            `archived`).
    """
    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(f"Lead {lead_id} not found")
        if lead.status not in _QUALIFIABLE_FROM:
            raise LeadCannotQualifyError(
                f"Lead {lead_id} is in status {lead.status}, cannot qualify"
            )

        created_client_id: int | None = None
        if lead.client_id is None:
            client = _maybe_build_client(lead)
            if client is not None:
                client = await uow.clients.add(client)
                lead.client_id = client.id
                created_client_id = client.id

        lead.status = LeadStatus.qualified

        await record_event(
            uow,
            event_type="lead.qualified",
            aggregate_type="lead",
            aggregate_id=lead.id,
            payload={"created_client_id": created_client_id},
            actor_user_id=operator_user_id,
        )

        await uow.commit()
        result = lead

    log.info(
        "qualify_lead.done",
        lead_id=lead_id,
        created_client_id=created_client_id,
    )
    return result


def _maybe_build_client(lead: Lead) -> Client | None:
    """Return a fresh Client built from extracted_data, or None.

    Heuristic: we need at least a non-empty ``full_name``. ``phone``,
    ``email``, and ``telegram_id`` are optional but populated when
    present in extracted_data.
    """
    data = lead.extracted_data or {}
    if data.get("_extraction_failed"):
        return None
    full_name = data.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        return None

    contact = data.get("contact")
    phone: str | None = None
    email: str | None = None
    if isinstance(contact, str):
        if "@" in contact:
            email = contact
        else:
            phone = contact

    return Client(
        full_name=full_name.strip(),
        phone=phone,
        email=email,
        source=ClientSource.telegram,
        notes="",
    )
```

- [ ] **Step 3: Lightweight unit test**

Create `tests/unit/test_qualify_lead_unit.py`:

```python
"""Unit tests for qualify_lead — covers status guards and client building."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.db.models.enums import LeadStatus
from crm.use_cases.qualify_lead import (
    LeadCannotQualifyError,
    LeadNotFoundError,
    qualify_lead,
)


def _container_with_lead(lead) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=lead)
    uow.clients = MagicMock()

    fake_client = MagicMock()
    fake_client.id = 555
    uow.clients.add = AsyncMock(return_value=fake_client)

    container = MagicMock()
    container.uow = MagicMock(return_value=uow)
    return container


@pytest.mark.asyncio
async def test_qualify_lead_not_found_raises() -> None:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(LeadNotFoundError):
        await qualify_lead(container, lead_id=1, operator_user_id=None)


@pytest.mark.asyncio
async def test_qualify_lead_terminal_status_raises() -> None:
    lead = MagicMock()
    lead.id = 1
    lead.status = LeadStatus.archived
    container = _container_with_lead(lead)

    with pytest.raises(LeadCannotQualifyError):
        await qualify_lead(container, lead_id=1, operator_user_id=None)
```

- [ ] **Step 4: Run tests**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_qualify_lead_unit.py tests/integration/test_qualify_lead.py -v
```

Expected: **2 unit + 5 integration = 7 passed**.

- [ ] **Step 5: Full suite**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 53 passed (46 + 7).

- [ ] **Step 6: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/use_cases/qualify_lead.py tests/unit/test_qualify_lead_unit.py tests/integration/test_qualify_lead.py
git commit -m "feat(use_cases): qualify_lead promotes Lead and optionally creates Client"
```

---

## Task 4: Bot handlers — text intake + callback qualify

**Files:**
- Modify: `src/crm/entrypoints/bot.py`
- Test: `tests/integration/test_bot_handlers.py`

The bot must:
- React to **any non-command text message** from an allowlisted operator → call `intake_lead`, reply with `{summary}` + inline keyboard `[✅ Подтвердить][✏ Править]`.
- React to **callback `confirm_lead:{id}`** → call `qualify_lead`, edit message to confirm.
- React to **callback `edit_lead:{id}`** → reply "Редактирование пока не реализовано" (placeholder for future plan).

- [ ] **Step 1: Replace `src/crm/entrypoints/bot.py`**

```python
"""aiogram bot entrypoint.

Translates Telegram events into use-case calls. No business logic here —
only routing, keyboard rendering, and operator allowlist gating.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher, Router, F
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


def _format_intake_reply(lead) -> str:  # noqa: ANN001
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
```

- [ ] **Step 2: Write integration test for handlers**

Create `tests/integration/test_bot_handlers.py`:

```python
"""Integration tests for the lead intake bot handlers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import LeadStatus
from crm.entrypoints.bot import register_handlers


def _alembic_config(settings: Settings) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def _migrate(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _make_text_update(text: str, *, user_id: int, msg_id: int = 1001, chat_id: int = 100) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=msg_id,
            date=__import__("datetime").datetime.now(__import__("datetime").UTC),
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Op"),
            text=text,
        ),
    )


def _make_callback_update(data: str, *, user_id: int, chat_id: int = 100) -> Update:
    return Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=user_id, is_bot=False, first_name="Op"),
            chat_instance="ci-1",
            data=data,
            message=Message(
                message_id=1002,
                date=__import__("datetime").datetime.now(__import__("datetime").UTC),
                chat=Chat(id=chat_id, type="private"),
                from_user=User(id=99, is_bot=True, first_name="bot"),
                text="prev",
            ),
        ),
    )


def _container_with_capturing_sender(
    settings: Settings,
) -> tuple[Container, list[dict]]:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]
    return container, sent


@pytest.mark.integration
async def test_bot_text_message_runs_intake_and_shows_keyboard(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container, sent = _container_with_capturing_sender(settings)

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = _make_text_update("Иван, дом 200 м2", user_id=operator_id)

    # Construct a minimal Bot stub — aiogram requires *some* bot for feed_update.
    bot_stub = MagicMock()
    bot_stub.id = 99
    bot_stub.session = MagicMock()
    bot_stub.session.close = AsyncMock()
    await dp.feed_update(bot_stub, update)

    assert len(sent) == 1
    payload = sent[0]
    assert "Lead #" in payload["text"]
    assert isinstance(payload["reply_markup"], InlineKeyboardMarkup)

    await container.aclose()


@pytest.mark.integration
async def test_bot_text_from_non_operator_is_ignored(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container, sent = _container_with_capturing_sender(settings)

    dp = Dispatcher()
    register_handlers(dp, container)

    update = _make_text_update("hi", user_id=987654321)  # not in allowlist

    bot_stub = MagicMock()
    bot_stub.id = 99
    await dp.feed_update(bot_stub, update)

    assert sent == []

    await container.aclose()


@pytest.mark.integration
async def test_bot_confirm_callback_qualifies_lead(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crm.db.models.enums import ChannelKind
    from crm.db.models.lead import Lead

    await _migrate(settings, monkeypatch)
    container, sent = _container_with_capturing_sender(settings)

    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                status=LeadStatus.qualifying,
                extracted_data={"full_name": "Тест"},
            )
        )
        await uow.commit()
        lead_id = lead.id

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = _make_callback_update(f"confirm_lead:{lead_id}", user_id=operator_id)

    bot_stub = MagicMock()
    bot_stub.id = 99
    bot_stub.answer_callback_query = AsyncMock()
    await dp.feed_update(bot_stub, update)

    assert len(sent) == 1
    assert f"Lead #{lead_id}" in sent[0]["text"]
    assert "qualified" in sent[0]["text"]

    async with container.uow() as uow:
        loaded = await uow.leads.get(lead_id)
    assert loaded is not None
    assert loaded.status == LeadStatus.qualified
    assert loaded.client_id is not None

    await container.aclose()
```

- [ ] **Step 3: Run tests**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_bot_handlers.py -v -m integration
```

Expected: **3 passed**.

If aiogram's `feed_update` complains about missing bot methods, add the missing `AsyncMock` attributes to `bot_stub` (e.g. `bot_stub.get_me = AsyncMock()`). Aim for the minimum stub surface.

- [ ] **Step 4: Existing bot test still passes**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_bot_start.py -v -m integration
```

Expected: 2 passed (the `/start` allowlist tests from Plan 1 still work).

- [ ] **Step 5: Full suite**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 56 passed (53 + 3).

- [ ] **Step 6: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/entrypoints/bot.py tests/integration/test_bot_handlers.py
git commit -m "feat(bot): text intake + confirm/edit callbacks calling use cases"
```

---

## Task 5: Tag `plan-3-lead-intake`

**Files:** none. This is a milestone tag.

- [ ] **Step 1: Verify state**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
git status
```

Expected: 56 passed, ruff clean, working tree clean.

- [ ] **Step 2: Tag**

```powershell
git tag -a plan-3-lead-intake -m "Plan 3: Lead Intake complete (intake_lead, qualify_lead, bot handlers, fake AI)"
git tag --list | findstr plan-3
```

Expected output includes `plan-3-lead-intake`.

---

## Task 6: Dependencies + prompt templates

**Files:**
- Modify: `pyproject.toml` (add `openai`, `jinja2`)
- Create: `src/crm/prompts/__init__.py`
- Create: `src/crm/prompts/extract_lead.j2`
- Create: `src/crm/prompts/generate_proposal.j2`
- Test: `tests/unit/test_prompts.py`

- [ ] **Step 1: Add deps**

Open `pyproject.toml`. Find the `dependencies = [` block in `[project]` and add two lines:

```toml
    "openai>=1.50",
    "jinja2>=3.1",
```

Run:

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" sync
```

Expected: installs `openai`, `jinja2`, their transitive deps. No lockfile conflicts.

- [ ] **Step 2: Create `src/crm/prompts/__init__.py`**

```python
"""Prompt-template rendering.

Templates live as ``.j2`` files alongside this module. ``render(name, **vars)``
loads the template from the package directory and returns the rendered text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATE_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, **variables: Any) -> str:
    """Render the named ``.j2`` template with the supplied variables.

    Raises a Jinja UndefinedError if the template references a variable
    that wasn't supplied (StrictUndefined). Use ``render('extract_lead',
    raw_text='...')``.
    """
    template = _env.get_template(template_name + ".j2")
    return template.render(**variables)
```

- [ ] **Step 3: Create `src/crm/prompts/extract_lead.j2`**

```jinja
You are a back-office assistant for an architecture bureau. Extract the
following fields from the operator-forwarded message below.

Message:
"""
{{ raw_text }}
"""

Return STRICT JSON with this shape (use null when not present):
{
  "full_name": string | null,
  "contact": string | null,
  "project_type": "apartment" | "house" | "commercial" | "renovation" | "other" | null,
  "area_m2": number | null,
  "budget_range": string | null,
  "timeline": string | null,
  "summary": string,
  "confidence": number
}

- "summary" is a 1-2 sentence Russian summary of the request.
- "confidence" is between 0 and 1.
- Do NOT include any text outside the JSON object.
```

- [ ] **Step 4: Create `src/crm/prompts/generate_proposal.j2`**

```jinja
You are a senior architect at a small bureau. Write a short, friendly draft
proposal in Russian based on the lead data below.

Lead summary:
"""
{{ lead_summary }}
"""

Extracted data (may have null fields):
{{ extracted_json }}

Return STRICT JSON:
{
  "body": string,             // proposal body in Russian, ~6-12 sentences
  "scope_summary": string,    // 1-sentence scope (Russian)
  "price_estimate": number | null,
  "currency": "RUB"
}

- "body" should mention next-step expectations (meeting, measurements, draft).
- "price_estimate" only if the brief gives enough info; otherwise null.
- Do NOT include any text outside the JSON object.
```

- [ ] **Step 5: Write the render() test**

Create `tests/unit/test_prompts.py`:

```python
from __future__ import annotations

import pytest

from crm.prompts import render


def test_render_extract_lead_template_contains_raw_text() -> None:
    out = render("extract_lead", raw_text="Иван дом 200 м2")
    assert "Иван дом 200 м2" in out
    assert '"full_name"' in out


def test_render_generate_proposal_template_contains_summary_and_json() -> None:
    out = render(
        "generate_proposal",
        lead_summary="apartment renovation",
        extracted_json='{"area_m2": 60}',
    )
    assert "apartment renovation" in out
    assert '"area_m2"' in out


def test_render_strict_undefined() -> None:
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        render("extract_lead")  # missing raw_text
```

- [ ] **Step 6: Run tests**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_prompts.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Full suite**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 59 passed (56 + 3).

- [ ] **Step 8: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add pyproject.toml uv.lock src/crm/prompts/ tests/unit/test_prompts.py
git commit -m "feat(prompts): jinja-rendered AI prompt templates + openai/jinja2 deps"
```

(Stage `uv.lock` if it changed; if your repo does not track it, omit.)

---

## Task 7: `OpenAIExtractor` implementation

**Files:**
- Create: `src/crm/adapters/ai/openai_extractor.py`
- Test: `tests/unit/test_openai_extractor.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_openai_extractor.py`:

```python
"""Unit tests for OpenAIExtractor with a mocked AsyncOpenAI client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.openai_extractor import OpenAIExtractor


def _completion_response(payload: dict) -> SimpleNamespace:
    """Build a minimal openai SDK-shaped response object."""
    msg = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice], model="gpt-5.5-medium")


@pytest.mark.asyncio
async def test_extract_parses_structured_json_response() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_completion_response(
            {
                "full_name": "Иван",
                "contact": "+7900xxx",
                "project_type": "house",
                "area_m2": 200,
                "budget_range": "3 млн",
                "timeline": "к маю",
                "summary": "Дом 200 м2, бюджет 3 млн, срок май.",
                "confidence": 0.85,
            }
        )
    )

    extractor = OpenAIExtractor(client=client, model="gpt-5.5-medium")
    result = await extractor.extract("Иван, дом 200 м2, бюджет 3 млн, к маю")

    assert result.full_name == "Иван"
    assert result.area_m2 == 200
    assert result.summary.startswith("Дом")
    assert result.confidence == 0.85
    assert "full_name" in result.raw_response
    client.chat.completions.create.assert_awaited_once()
    call = client.chat.completions.create.await_args
    assert call.kwargs["model"] == "gpt-5.5-medium"
    assert call.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_extract_tolerates_missing_optional_fields() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_completion_response(
            {
                "summary": "Ремонт без деталей.",
                "confidence": 0.4,
            }
        )
    )

    extractor = OpenAIExtractor(client=client, model="gpt-5.5-medium")
    result = await extractor.extract("Ремонт")

    assert result.full_name is None
    assert result.area_m2 is None
    assert result.summary == "Ремонт без деталей."
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_extract_invalid_json_raises_value_error() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    choice = SimpleNamespace(message=SimpleNamespace(content="not json"))
    response = SimpleNamespace(choices=[choice], model="gpt-5.5-medium")
    client.chat.completions.create = AsyncMock(return_value=response)

    extractor = OpenAIExtractor(client=client, model="gpt-5.5-medium")

    with pytest.raises(ValueError, match="invalid JSON"):
        await extractor.extract("anything")
```

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_openai_extractor.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 2: Create `src/crm/adapters/ai/openai_extractor.py`**

```python
"""OpenAI implementation of the AIExtractor protocol.

Uses chat completions with ``response_format={"type": "json_object"}`` and
a Jinja-rendered system prompt. The model is instructed (via the prompt)
to return strictly the documented JSON shape; we parse + coerce here.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import structlog

from crm.adapters.ai.extractor import ExtractedLead
from crm.prompts import render

log = structlog.get_logger(__name__)


class _OpenAIClientLike(Protocol):
    """Subset of openai.AsyncOpenAI we depend on — kept narrow for testing."""

    chat: Any


class OpenAIExtractor:
    """Calls OpenAI to extract structured fields from a raw lead message."""

    def __init__(self, *, client: _OpenAIClientLike, model: str) -> None:
        self._client = client
        self._model = model

    async def extract(self, raw_text: str) -> ExtractedLead:
        prompt = render("extract_lead", raw_text=raw_text)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        try:
            data: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as exc:
            log.warning(
                "openai_extractor.invalid_json",
                model=self._model,
                content_head=content[:200],
            )
            raise ValueError(f"OpenAI returned invalid JSON: {exc}") from exc

        return ExtractedLead(
            full_name=_str_or_none(data.get("full_name")),
            contact=_str_or_none(data.get("contact")),
            project_type=_str_or_none(data.get("project_type")),
            area_m2=_float_or_none(data.get("area_m2")),
            budget_range=_str_or_none(data.get("budget_range")),
            timeline=_str_or_none(data.get("timeline")),
            summary=_str_or_none(data.get("summary")) or "",
            confidence=_float_or_none(data.get("confidence")) or 0.0,
            raw_response=data,
        )


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 3: Run unit tests**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_openai_extractor.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Full suite + ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/adapters/ai/openai_extractor.py tests/unit/test_openai_extractor.py
git commit -m "feat(adapters): OpenAIExtractor with JSON-mode response_format"
```

Expected: 62 passed.

---

## Task 8: Container switch + smoke integration test

**Files:**
- Modify: `src/crm/container.py`
- Test: `tests/integration/test_intake_lead.py` (add one smoke test)

- [ ] **Step 1: Inspect current `src/crm/container.py`**

Read it. We need to find the `ai_extractor` assignment and replace it with a function that branches on `settings.ai_provider`.

- [ ] **Step 2: Patch `src/crm/container.py`**

Locate the existing line that constructs `ai_extractor` (likely `self.ai_extractor = FakeAIExtractor()` or similar). Replace with a call to a new `_build_ai_extractor(settings)` factory defined at module level. Likewise for `proposal_writer`.

Add at the top of the file (after existing imports):

```python
from crm.adapters.ai.extractor import AIExtractor, FakeAIExtractor
from crm.adapters.ai.openai_extractor import OpenAIExtractor
from crm.adapters.ai.proposal_writer import (
    FakeProposalWriter,
    ProposalWriter,
)
```

If those imports already exist, just merge the new lines (`OpenAIExtractor`).

Add these module-level factories above `class Container`:

```python
def _build_ai_extractor(settings: Settings) -> AIExtractor:
    provider = settings.ai_provider.lower()
    if provider == "openai":
        from openai import AsyncOpenAI

        if not settings.openai_api_key:
            raise RuntimeError(
                "AI_PROVIDER=openai but OPENAI_API_KEY is not set"
            )
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return OpenAIExtractor(client=client, model=settings.openai_model)
    if provider == "fake":
        return FakeAIExtractor()
    raise RuntimeError(f"Unsupported AI_PROVIDER: {settings.ai_provider!r}")


def _build_proposal_writer(settings: Settings) -> ProposalWriter:
    provider = settings.ai_provider.lower()
    if provider == "openai":
        from crm.adapters.ai.openai_proposal_writer import OpenAIProposalWriter
        from openai import AsyncOpenAI

        if not settings.openai_api_key:
            raise RuntimeError(
                "AI_PROVIDER=openai but OPENAI_API_KEY is not set"
            )
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return OpenAIProposalWriter(client=client, model=settings.openai_model)
    if provider == "fake":
        return FakeProposalWriter()
    raise RuntimeError(f"Unsupported AI_PROVIDER: {settings.ai_provider!r}")
```

Inside `Container.__init__`, replace the two assignments:

```python
self.ai_extractor: AIExtractor = _build_ai_extractor(settings)
self.proposal_writer: ProposalWriter = _build_proposal_writer(settings)
```

**If `Settings` doesn't yet have `openai_api_key` / `openai_model`**: open `src/crm/config.py`, find the existing fields, and add:

```python
    openai_api_key: str = ""
    openai_model: str = "gpt-5.5-medium"
```

(They are in `.env.example` already from Plan 1; just expose them in pydantic-settings.)

The `OpenAIProposalWriter` import is **inside the function** so the test suite without OpenAI keys can still import `Container` when provider != openai.

- [ ] **Step 3: Smoke integration test — provider=fake still works end-to-end**

Open `tests/integration/test_intake_lead.py` (already created in Task 2) and append:

```python
@pytest.mark.integration
async def test_intake_lead_works_with_fake_provider_via_container_factory(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-trip: Container(settings) where ai_provider=fake builds a usable extractor."""
    from crm.adapters.ai.extractor import FakeAIExtractor

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    assert isinstance(container.ai_extractor, FakeAIExtractor)

    lead = await intake_lead(
        container,
        raw_text="smoke",
        channel=ChannelKind.telegram,
        channel_message_id="tg:smoke",
        operator_user_id=None,
    )
    assert lead.status == LeadStatus.qualifying

    await container.aclose()
```

- [ ] **Step 4: Unit test for the factory branching**

Append to `tests/unit/test_container.py` (Plan 1 file):

```python
import pytest


def test_build_ai_extractor_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm.adapters.ai.extractor import FakeAIExtractor
    from crm.config import Settings
    from crm.container import _build_ai_extractor

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "1")
    monkeypatch.setenv("AI_PROVIDER", "fake")
    settings = Settings()  # type: ignore[call-arg]

    extractor = _build_ai_extractor(settings)
    assert isinstance(extractor, FakeAIExtractor)


def test_build_ai_extractor_openai_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm.config import Settings
    from crm.container import _build_ai_extractor

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "1")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = Settings()  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _build_ai_extractor(settings)


def test_build_ai_extractor_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm.config import Settings
    from crm.container import _build_ai_extractor

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "1")
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    settings = Settings()  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="Unsupported AI_PROVIDER"):
        _build_ai_extractor(settings)
```

- [ ] **Step 5: Run all touched tests**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_container.py tests/integration/test_intake_lead.py -v
```

Expected: passes.

- [ ] **Step 6: Full suite**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 66 passed (62 + 3 unit + 1 integration).

- [ ] **Step 7: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/container.py src/crm/config.py tests/unit/test_container.py tests/integration/test_intake_lead.py
git commit -m "feat(container): switch AI extractor/writer by AI_PROVIDER (fake|openai)"
```

---

## Task 9: `OpenAIProposalWriter` implementation

**Files:**
- Create: `src/crm/adapters/ai/openai_proposal_writer.py`
- Test: `tests/unit/test_openai_proposal_writer.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_openai_proposal_writer.py`:

```python
"""Unit tests for OpenAIProposalWriter with a mocked AsyncOpenAI client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.openai_proposal_writer import OpenAIProposalWriter


def _resp(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
        ],
        model="gpt-5.5-medium",
    )


@pytest.mark.asyncio
async def test_generate_parses_full_payload() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_resp(
            {
                "body": "Здравствуйте! Спасибо за обращение. ...",
                "scope_summary": "Ремонт квартиры 60 м2",
                "price_estimate": 350000,
                "currency": "RUB",
            }
        )
    )

    writer = OpenAIProposalWriter(client=client, model="gpt-5.5-medium")
    draft = await writer.generate(
        lead_summary="renovation",
        extracted={"area_m2": 60},
    )

    assert draft.body.startswith("Здравствуйте")
    assert draft.scope_summary.startswith("Ремонт")
    assert draft.price_estimate == 350000
    assert draft.currency == "RUB"

    call = client.chat.completions.create.await_args
    assert call.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_generate_tolerates_missing_price() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_resp(
            {
                "body": "Привет!",
                "scope_summary": "scope",
                "currency": "RUB",
            }
        )
    )

    writer = OpenAIProposalWriter(client=client, model="gpt-5.5-medium")
    draft = await writer.generate(lead_summary="x", extracted={})

    assert draft.price_estimate is None
    assert draft.currency == "RUB"


@pytest.mark.asyncio
async def test_generate_invalid_json_raises() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    bad = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="garbage"))],
        model="gpt-5.5-medium",
    )
    client.chat.completions.create = AsyncMock(return_value=bad)

    writer = OpenAIProposalWriter(client=client, model="gpt-5.5-medium")

    with pytest.raises(ValueError, match="invalid JSON"):
        await writer.generate(lead_summary="x", extracted={})
```

- [ ] **Step 2: Create `src/crm/adapters/ai/openai_proposal_writer.py`**

```python
"""OpenAI implementation of the ProposalWriter protocol."""

from __future__ import annotations

import json
from typing import Any, Protocol

import structlog

from crm.adapters.ai.proposal_writer import ProposalDraft
from crm.prompts import render

log = structlog.get_logger(__name__)


class _OpenAIClientLike(Protocol):
    chat: Any


class OpenAIProposalWriter:
    """Generates a proposal draft via OpenAI."""

    def __init__(self, *, client: _OpenAIClientLike, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self, *, lead_summary: str, extracted: dict
    ) -> ProposalDraft:
        prompt = render(
            "generate_proposal",
            lead_summary=lead_summary,
            extracted_json=json.dumps(extracted, ensure_ascii=False),
        )
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        try:
            data: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as exc:
            log.warning(
                "openai_proposal_writer.invalid_json",
                model=self._model,
                content_head=content[:200],
            )
            raise ValueError(f"OpenAI returned invalid JSON: {exc}") from exc

        return ProposalDraft(
            body=str(data.get("body") or ""),
            scope_summary=str(data.get("scope_summary") or ""),
            price_estimate=_float_or_none(data.get("price_estimate")),
            currency=str(data.get("currency") or "RUB"),
        )


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 3: Run unit tests + full suite**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_openai_proposal_writer.py -v
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 3 passed for the new file; full suite: 69 passed (66 + 3).

- [ ] **Step 4: Ruff + commit**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/adapters/ai/openai_proposal_writer.py tests/unit/test_openai_proposal_writer.py
git commit -m "feat(adapters): OpenAIProposalWriter for Plan 5 use cases"
```

---

## Task 10: README + tag `plan-4-ai-adapters`

**Files:**
- Modify: `README.md`
- Tag: `plan-4-ai-adapters`

- [ ] **Step 1: Update README status**

Replace:

```markdown
- [x] Plan 2: Domain + Schema
- [ ] Plan 3: Lead Intake (fake AI)
- [ ] Plan 4: AI Adapters
- [ ] Plan 5: Proposal + Scheduler + Worker
```

with:

```markdown
- [x] Plan 2: Domain + Schema
- [x] Plan 3: Lead Intake (fake AI)
- [x] Plan 4: AI Adapters (OpenAI)
- [ ] Plan 5: Proposal + Scheduler + Worker
```

In the "Architecture in 30 seconds" section, find:

```
domain tables (Plan 2):
  ...
```

Add below it:

```
use cases (Plan 3):
  intake_lead  qualify_lead

AI adapters (Plan 4):
  OpenAIExtractor (gpt-5.5-medium)  OpenAIProposalWriter
  prompts in src/crm/prompts/*.j2
```

- [ ] **Step 2: Final verification**

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format --check .
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 69 passed, ruff green.

- [ ] **Step 3: Commit + tag**

```powershell
git add README.md
git commit -m "docs(domain): update README - Plan 3+4 complete (lead intake + OpenAI)"

git tag -a plan-4-ai-adapters -m "Plan 4: AI Adapters complete (OpenAIExtractor + OpenAIProposalWriter + prompts)"
git log --oneline -5
git tag --list | findstr plan-
```

Expected: tag list shows `plan-1-foundation`, `plan-2-domain-schema`, `plan-3-lead-intake`, `plan-4-ai-adapters`.

---

## Self-Review checklist

**Spec coverage:**

| Spec section | Tasks |
|---|---|
| §5.1 steps 1-5 (intake) | Task 2 |
| §5.1 step 7 (qualify) | Task 3 |
| §5.2 `intake_lead` use case | Task 2 |
| §5.2 `qualify_lead` use case | Task 3 |
| §5.3 AI calls sync, **outside** transaction | Task 2 (TX1 → AI → TX2) |
| §5.4 AI failure → save lead anyway | Task 2 step 2 (extraction_failed branch) |
| §5.5 status map (new → qualifying → qualified) | Tasks 2, 3 |
| §6.1 events written explicitly in same txn | Task 1 + 2 + 3 |
| §6.3 `build_ai_extractor(settings)` | Task 8 |
| §6.3 ExtractedLead dataclass shape | Already present from Plan 1 |
| §11 prompts in `prompts/` as `.j2` | Task 6 |

**Placeholder scan:** No "TBD", every step has code or commands.

**Type consistency:**
- `intake_lead`/`qualify_lead` both take `Container` as first positional arg. Consistent.
- Both use `record_event` helper. Consistent.
- `OpenAIExtractor` and `OpenAIProposalWriter` both take `client` and `model` kwargs. Consistent.
- `_build_ai_extractor` / `_build_proposal_writer` both raise `RuntimeError` on missing key. Consistent.

---

## Definition of Done

- [ ] `uv sync` succeeds with new deps (`openai`, `jinja2`).
- [ ] `uv run pytest` is green; expected count ≈ 69.
- [ ] `uv run ruff check .` and `ruff format --check .` are green.
- [ ] Tag `plan-3-lead-intake` exists at end of T5.
- [ ] Tag `plan-4-ai-adapters` exists at end of T10.
- [ ] `intake_lead` end-to-end works with `AI_PROVIDER=fake`.
- [ ] `intake_lead` end-to-end importable with `AI_PROVIDER=openai` (skipped at runtime if no key, but `_build_ai_extractor` raises a clear error).
- [ ] Bot text handler routes through `intake_lead`; confirm callback routes through `qualify_lead`; both verified by integration tests.

---

## Backlog brought forward to Plan 5+

- Integration test isolation (per-test DB truncation).
- `ScheduledJobRepository.mark_running` → `session.refresh(job)` in worker.
- `users.is_active` server_default.
- Manual re-extract trigger for leads with `_extraction_failed`.
- Bot "Edit lead" callback — implement when state machine arrives.

---

## Execution handoff

**Plan complete and saved. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task with combined spec+quality review between tasks. Worked well for Plan 1 + 2.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans` with checkpoints after T5 (Plan 3 boundary) and T10 (Plan 4 boundary).

**Which approach?**
