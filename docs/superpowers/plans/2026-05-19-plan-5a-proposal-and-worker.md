# Plan 5a: Proposal Generation + Worker Infrastructure + GDocs Publishing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement steps 8–18 of the spec §5.1 happy path: AI-generated `Proposal` drafts from a qualified lead, the `scheduled_jobs` worker (poll loop, lease, backoff), and asynchronous publication of a proposal into a Google Doc with operator notification.

**Scope split:** This is Plan **5a**. Plan **5b** (next) will add `mark_proposal_sent`, `FollowUp` lifecycle, `send_follow_up`, and `record_follow_up_result`.

**Architecture:** Same patterns as Plan 3+4. Use cases live in `src/crm/use_cases/<name>.py` with explicit Container dependency. The new worker package `src/crm/scheduler/` owns the queue primitives (`enqueue_job`, backoff, reclaim) and the poll loop. Job handlers register themselves via a module-level dict in `src/crm/scheduler/handlers.py` to keep the loop decoupled from concrete use cases. AI calls happen **outside** any DB transaction (spec §6.3) for both proposal generation and inside the worker's GDocs job.

**Tech additions:** None — `openai`, `jinja2`, `aiogram` already pinned in Plan 3+4.

---

## Branch

```powershell
cd C:\Repos\reyzbikh_buro_crm
git checkout main
git pull --ff-only origin main
git checkout -b plan-5a-proposal-and-worker
```

One tag at the end: `plan-5a-proposal-and-worker`.

---

## Prerequisites

Already in place from Plan 3+4 (HEAD = `2139efc` on main):
- `ProposalWriter` Protocol + `ProposalDraft` dataclass + `FakeProposalWriter` + `OpenAIProposalWriter`.
- `GDocsClient` Protocol + `GDocRef` dataclass + `FakeGDocsClient`.
- `ScheduledJobRepository.{get_by_idempotency_key, list_pending_due, mark_running}` (Plan 2).
- `Container` builds all fakes; `AI_PROVIDER` switch (Plan 4).
- `record_event` helper (Plan 3).
- Bot's `/start` handler + lead intake + qualify (Plan 3).
- 69 tests passing.

Sanity check:

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
docker info
```

Expected: 69 passed, ruff clean.

---

## File Structure

### Created in this plan

```
src/crm/
  scheduler/
    __init__.py                   # docstring
    jobs.py                       # enqueue_job(), apply_backoff(), constants
    handlers.py                   # JOB_HANDLERS registry + JobHandler type
    runner.py                     # run_worker() main poll loop, execute_job()
  use_cases/
    generate_proposal.py          # AI-driven proposal draft
    publish_proposal_to_gdoc.py   # enqueue-only use case
  prompts/
    # already created in Plan 3+4: extract_lead.j2, generate_proposal.j2

tests/
  unit/
    test_enqueue_job.py
    test_generate_proposal_unit.py
    test_publish_proposal_to_gdoc_unit.py
    test_scheduler_backoff.py
  integration/
    test_generate_proposal.py
    test_publish_proposal_to_gdoc.py
    test_worker_runner.py         # full pick-execute-mark_done flow
    test_worker_publish_gdoc.py   # end-to-end: enqueue + worker runs handler
    test_bot_propose_callback.py  # bot button: "Сгенерировать предложение"
    test_bot_publish_callback.py  # bot button: "В Google Doc"
```

### Modified in this plan

```
migrations/env.py                          # prefer Config-supplied URL over Settings
src/crm/db/repositories/scheduled_jobs.py  # + mark_done, reschedule, reclaim_stuck
src/crm/db/repositories/proposals.py       # add list_by_lead, get_with_lock helpers
src/crm/db/repositories/documents.py       # add list_by_owner(owner_type, owner_id)
src/crm/entrypoints/worker.py              # actually run the worker (was a stub)
src/crm/entrypoints/bot.py                 # add propose + publish callbacks
tests/integration/conftest.py              # session-scoped migrate + per-test db_clean
tests/integration/test_*.py                # adopt new fixtures (remove inline _migrate)
README.md                                  # bump status to Plan 5a
```

---

## Conventions

- `uv` lives at `& "$env:USERPROFILE\.local\bin\uv.exe"`.
- All datetimes are timezone-aware (`datetime.now(UTC)`).
- The worker uses a per-job transaction with FOR UPDATE SKIP LOCKED. Failure inside a handler raises; the runner converts the exception into either a `reschedule` (with backoff) or `mark_failed_terminal` based on `attempts` vs `max_attempts`.
- Handler invariants: do NOT swallow exceptions inside a handler; do NOT commit on behalf of the runner — handlers manage their OWN UoW for the actual domain work.
- Tests run under `pytest-asyncio` with `asyncio_mode = auto` (already configured).

---

## Task 1: Test isolation refactor

**Files:**
- Modify: `migrations/env.py`
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/test_repositories.py`
- Modify: `tests/integration/test_intake_lead.py`
- Modify: `tests/integration/test_qualify_lead.py`
- Modify: `tests/integration/test_bot_handlers.py`
- Modify: `tests/integration/test_bot_start.py`
- Keep: `tests/integration/test_migrations.py` (it explicitly tests upgrade/downgrade flow; uses its own migrate; just confirm it still passes)

**Why:** Plan 2/3 backlog item. The shared session-scoped Postgres container leaks rows between tests. Several test files added ad-hoc `_cleanup_lead` / `_teardown_lead` helpers. With Plan 5 adding worker tests that create + execute jobs, this only gets worse.

**Solution:**
1. Make `migrations/env.py` honor a pre-set `sqlalchemy.url` on the Alembic Config (fallback to Settings if absent) — lets tests skip the `monkeypatch.setenv` ritual.
2. Add a **session-scoped** `migrated` fixture that runs `alembic upgrade head` once per test session.
3. Add a **function-scoped** `db_clean` fixture that does `TRUNCATE ... RESTART IDENTITY CASCADE` on all domain tables before each test.
4. Convert existing tests to use both fixtures; delete their inline `_migrate` and inline cleanup helpers.

### Step 1: Patch `migrations/env.py` — prefer Config-supplied URL

Replace the `_get_url()` function with:

```python
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
```

### Step 2: Replace `tests/integration/conftest.py`

Full content:

```python
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

# Tables to truncate between tests. Keep in dependency-safe order.
# CASCADE handles FKs but using RESTART IDENTITY resets bigserial counters
# so test assertions on id values are stable.
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
    """Return a Postgres URL with the asyncpg driver regardless of testcontainers version."""
    raw = pg_container.get_connection_url()
    for old in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql://",
    ):
        if raw.startswith(old):
            return "postgresql+asyncpg://" + raw[len(old) :]
    return raw  # already on +asyncpg


@pytest.fixture
def settings(pg_url: str) -> Settings:
    # Telegram token must match aiogram's regex `\d+:[A-Za-z0-9_-]{35,}`
    # because some bot tests pass this value into `Bot(token=...)`.
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
    """Run alembic upgrade head once for the session."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    return pg_url


@pytest_asyncio.fixture
async def db_clean(engine: AsyncEngine, _migrated: str) -> AsyncIterator[None]:
    """Truncate all domain tables before each test.

    Depends on ``_migrated`` so the very first test triggers the one-shot
    migration. The truncate happens BEFORE the test body, so the test sees
    an empty database; we do not truncate again at teardown — the next
    test will do it.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE TABLE {', '.join(_DOMAIN_TABLES)} RESTART IDENTITY CASCADE")
        )
    yield
```

### Step 3: Refactor `tests/integration/test_intake_lead.py`

Drop:
- `_alembic_config` function.
- `_migrate` helper.
- Per-test cleanup blocks (`_teardown_lead`, manual `delete(...)` calls).
- `monkeypatch` arg where it was only used for migrate.

Each test signature becomes:
```python
async def test_intake_lead_happy_path_creates_lead_and_extracts(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    lead = await intake_lead(...)
    ...
    await container.aclose()
```

(`db_clean` is requested by name so pytest runs it. Body assertions don't change.)

### Step 4: Refactor `tests/integration/test_qualify_lead.py` and `test_bot_handlers.py` the same way

Same drill: remove `_migrate`, `_alembic_config`, and inline cleanup; add `db_clean` to test signatures; drop `monkeypatch` args.

### Step 5: Refactor `tests/integration/test_repositories.py`

Add `db_clean` to every test that creates rows; drop any existing `_migrate` helper if present; let each test start with an empty DB.

### Step 6: `tests/integration/test_bot_start.py`

Inspect the file. If it doesn't touch DB rows directly, just add `db_clean` for parity. If it has its own migrate logic, replace with `_migrated` fixture.

### Step 7: `tests/integration/test_migrations.py`

This file explicitly tests `alembic upgrade head → downgrade base → upgrade head` round-trips. It must **not** depend on `_migrated` (since its whole point is to control migration state). Leave its existing logic intact. Confirm it still passes after the env.py change.

### Step 8: Run full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **69 passed** (no net new tests; same count).

### Step 9: Ruff

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .
```

### Step 10: Commit

```
git add migrations/env.py tests/integration/conftest.py tests/integration/test_*.py
git commit -m "test(integration): session-scoped migrate + per-test db_clean fixture"
```

---

## Task 2: `generate_proposal` use case

**Files:**
- Create: `src/crm/use_cases/generate_proposal.py`
- Create: `tests/unit/test_generate_proposal_unit.py`
- Create: `tests/integration/test_generate_proposal.py`

**Contract** (spec §5.1 steps 8-11, §5.2):

```python
async def generate_proposal(
    container: Container,
    *,
    lead_id: int,
    operator_user_id: int | None,
) -> Proposal: ...
```

**Flow:**
1. **Txn 1**: Validate lead exists, status in `{qualified}`. Insert `Proposal(lead_id, version=1, status=draft, generated_text="", scope_summary="")`. Record event `proposal.created`. Commit. Capture proposal_id.
2. **Outside txn**: `draft = await container.proposal_writer.generate(lead_summary=lead.summary, extracted=lead.extracted_data)`.
3. **Txn 2 on success**: Update Proposal with `generated_text=draft.body`, `scope_summary=draft.scope_summary`, `price_estimate`, `currency`. Record event `proposal.generated`. Commit.
4. **Txn 2 on failure**: Leave generated_text=""; record event `proposal.generation_failed` with error. Commit.
5. Return Proposal.

**Errors:**
- `LeadNotFoundError` (already exists, import from `qualify_lead`).
- New: `LeadNotQualifiedError` — raised when lead is not in status `qualified`.

### Step 1: Write integration test (TDD)

Create `tests/integration/test_generate_proposal.py`:

```python
"""Integration tests for generate_proposal."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.adapters.ai.proposal_writer import ProposalDraft
from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.use_cases.generate_proposal import (
    LeadNotQualifiedError,
    generate_proposal,
)
from crm.use_cases.qualify_lead import LeadNotFoundError


async def _seed_qualified_lead(container: Container) -> int:
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="raw",
                summary="kitchen renovation, 60 m2",
                extracted_data={"area_m2": 60, "project_type": "renovation"},
                status=LeadStatus.qualified,
            )
        )
        await uow.commit()
        return lead.id


@pytest.mark.integration
async def test_generate_proposal_happy_path_creates_draft_and_fills_it(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    lead_id = await _seed_qualified_lead(container)

    proposal = await generate_proposal(
        container, lead_id=lead_id, operator_user_id=None
    )

    assert proposal.status == ProposalStatus.draft
    assert proposal.lead_id == lead_id
    assert proposal.version == 1
    assert proposal.generated_text  # FakeProposalWriter returns a non-empty body
    assert proposal.scope_summary

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("proposal", proposal.id)
    types = [e.event_type for e in events]
    assert "proposal.created" in types
    assert "proposal.generated" in types

    await container.aclose()


@pytest.mark.integration
async def test_generate_proposal_handles_ai_failure(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    class BrokenWriter:
        async def generate(self, *, lead_summary: str, extracted: dict) -> ProposalDraft:
            raise RuntimeError("AI is down")

    container = Container(settings)
    container.proposal_writer = BrokenWriter()  # type: ignore[assignment]
    lead_id = await _seed_qualified_lead(container)

    proposal = await generate_proposal(
        container, lead_id=lead_id, operator_user_id=None
    )

    assert proposal.status == ProposalStatus.draft
    assert proposal.generated_text == ""

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("proposal", proposal.id)
    types = [e.event_type for e in events]
    assert "proposal.created" in types
    assert "proposal.generation_failed" in types
    assert "proposal.generated" not in types

    await container.aclose()


@pytest.mark.integration
async def test_generate_proposal_rejects_missing_lead(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    with pytest.raises(LeadNotFoundError):
        await generate_proposal(container, lead_id=99_999, operator_user_id=None)
    await container.aclose()


@pytest.mark.integration
async def test_generate_proposal_rejects_non_qualified_lead(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                status=LeadStatus.new,
            )
        )
        await uow.commit()
        lead_id = lead.id

    with pytest.raises(LeadNotQualifiedError):
        await generate_proposal(container, lead_id=lead_id, operator_user_id=None)

    await container.aclose()
```

Run: expects `ModuleNotFoundError`.

### Step 2: Create `src/crm/use_cases/generate_proposal.py`

```python
"""generate_proposal use case.

Spec §5.1 steps 8-11. Two transactions:

  TX1: validate lead is qualified, INSERT Proposal(status=draft, version=1)
       and record event proposal.created.
  --- AI proposal_writer.generate(...) runs OUTSIDE any DB transaction ---
  TX2 (success): UPDATE Proposal with body/scope/price/currency, record
       event proposal.generated.
  TX2 (failure): leave generated_text="", record event
       proposal.generation_failed with the error string. Operator can
       re-trigger generation later.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import LeadStatus, ProposalStatus
from crm.db.models.proposal import Proposal
from crm.use_cases.events import record_event
from crm.use_cases.qualify_lead import LeadNotFoundError

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)


class LeadNotQualifiedError(ValueError):
    """Lead is not in status qualified — cannot generate a proposal."""


async def generate_proposal(
    container: Container,
    *,
    lead_id: int,
    operator_user_id: int | None,
) -> Proposal:
    """Create a draft Proposal and fill it via AI proposal writer."""
    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(f"Lead {lead_id} not found")
        if lead.status != LeadStatus.qualified:
            raise LeadNotQualifiedError(
                f"Lead {lead_id} status={lead.status}, must be qualified"
            )

        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead_id,
                version=1,
                status=ProposalStatus.draft,
                generated_text="",
                scope_summary="",
                currency="RUB",
            )
        )
        await record_event(
            uow,
            event_type="proposal.created",
            aggregate_type="proposal",
            aggregate_id=proposal.id,
            payload={"lead_id": lead_id, "version": 1},
            actor_user_id=operator_user_id,
        )
        lead_summary = lead.summary or ""
        extracted_snapshot = dict(lead.extracted_data or {})
        await uow.commit()
        proposal_id = proposal.id

    log.info("generate_proposal.created", proposal_id=proposal_id, lead_id=lead_id)

    try:
        draft = await container.proposal_writer.generate(
            lead_summary=lead_summary,
            extracted=extracted_snapshot,
        )
        generation_error: Exception | None = None
    except Exception as exc:
        log.warning(
            "generate_proposal.failed",
            proposal_id=proposal_id,
            error=str(exc),
        )
        draft = None
        generation_error = exc

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise RuntimeError(
                f"generate_proposal: Proposal {proposal_id} disappeared between TX1 and TX2"
            )

        if draft is not None:
            proposal.generated_text = draft.body
            proposal.scope_summary = draft.scope_summary
            proposal.price_estimate = (
                Decimal(str(draft.price_estimate))
                if draft.price_estimate is not None
                else None
            )
            proposal.currency = draft.currency or "RUB"
            await record_event(
                uow,
                event_type="proposal.generated",
                aggregate_type="proposal",
                aggregate_id=proposal_id,
                payload={
                    "scope_summary": draft.scope_summary,
                    "price_estimate": (
                        float(draft.price_estimate)
                        if draft.price_estimate is not None
                        else None
                    ),
                    "currency": proposal.currency,
                    "body_chars": len(draft.body),
                },
                actor_user_id=operator_user_id,
            )
        else:
            if generation_error is None:
                raise RuntimeError(
                    "generate_proposal: invariant broken — draft is None but no error"
                )
            await record_event(
                uow,
                event_type="proposal.generation_failed",
                aggregate_type="proposal",
                aggregate_id=proposal_id,
                payload={"error": str(generation_error)},
                actor_user_id=operator_user_id,
            )

        await uow.commit()
        result = proposal

    log.info(
        "generate_proposal.finished",
        proposal_id=proposal_id,
        ai_ok=generation_error is None,
    )
    return result
```

### Step 3: Lightweight unit test

Create `tests/unit/test_generate_proposal_unit.py`:

```python
"""Unit tests for generate_proposal — wiring & error paths without DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.proposal_writer import ProposalDraft
from crm.db.models.enums import LeadStatus, ProposalStatus
from crm.use_cases.generate_proposal import (
    LeadNotQualifiedError,
    generate_proposal,
)
from crm.use_cases.qualify_lead import LeadNotFoundError


def _stub_uow(lead, proposal_returned, proposal_loaded) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=lead)
    uow.proposals = MagicMock()
    uow.proposals.add = AsyncMock(return_value=proposal_returned)
    uow.proposals.get = AsyncMock(return_value=proposal_loaded)
    return uow


@pytest.mark.asyncio
async def test_generate_proposal_calls_ai_outside_transaction() -> None:
    lead = MagicMock()
    lead.id = 1
    lead.status = LeadStatus.qualified
    lead.summary = "kitchen"
    lead.extracted_data = {"area_m2": 60}

    proposal = MagicMock()
    proposal.id = 7
    proposal.status = ProposalStatus.draft
    proposal.generated_text = ""
    proposal.scope_summary = ""

    uow1 = _stub_uow(lead, proposal, proposal)
    uow2 = _stub_uow(lead, proposal, proposal)

    container = MagicMock()
    container.uow = MagicMock(side_effect=[uow1, uow2])
    container.proposal_writer = MagicMock()
    container.proposal_writer.generate = AsyncMock(
        return_value=ProposalDraft(
            body="hello",
            scope_summary="scope",
            price_estimate=12345.0,
            currency="RUB",
        )
    )

    result = await generate_proposal(container, lead_id=1, operator_user_id=None)

    assert result.generated_text == "hello"
    assert result.scope_summary == "scope"
    container.proposal_writer.generate.assert_awaited_once_with(
        lead_summary="kitchen", extracted={"area_m2": 60}
    )
    assert uow1.commit.await_count == 1
    assert uow2.commit.await_count == 1


@pytest.mark.asyncio
async def test_generate_proposal_lead_not_found() -> None:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(LeadNotFoundError):
        await generate_proposal(container, lead_id=1, operator_user_id=None)


@pytest.mark.asyncio
async def test_generate_proposal_lead_not_qualified() -> None:
    lead = MagicMock()
    lead.id = 1
    lead.status = LeadStatus.qualifying
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=lead)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(LeadNotQualifiedError):
        await generate_proposal(container, lead_id=1, operator_user_id=None)
```

### Step 4: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_generate_proposal_unit.py tests/integration/test_generate_proposal.py -v
```

Expected: 3 unit + 4 integration = 7 passed.

### Step 5: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **76 passed** (69 + 7).

### Step 6: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/use_cases/generate_proposal.py tests/unit/test_generate_proposal_unit.py tests/integration/test_generate_proposal.py
git commit -m "feat(use_cases): generate_proposal — AI-drafted proposal from qualified lead"
```

---

## Task 3: Bot handler — "Сгенерировать предложение"

**Files:**
- Modify: `src/crm/entrypoints/bot.py` (add new callback prefix + handler)
- Create: `tests/integration/test_bot_propose_callback.py`

The qualify-confirmation reply already exists. We extend it to include a "📝 Сгенерировать предложение" button when the lead is freshly qualified, and add a callback handler for it.

### Step 1: Patch `src/crm/entrypoints/bot.py`

Add at the top of the constant block:

```python
PROPOSE_PREFIX = "propose_lead:"
```

Update the `on_confirm` handler's success reply to include a propose button. Find:

```python
        if cb.message is not None:
            await container.telegram_sender.send_message(
                chat_id=cb.message.chat.id,
                text=(
                    f"Lead #{lead.id} → qualified."
                    ...
                ),
            )
```

Replace with:

```python
        if cb.message is not None:
            text = (
                f"Lead #{lead.id} → qualified."
                + (
                    f" Создан Client #{lead.client_id}."
                    if lead.client_id
                    else " Client не создан (нет имени в данных)."
                )
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
```

Add a new handler after `on_edit`:

```python
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
            proposal = await generate_proposal(
                container, lead_id=lead_id, operator_user_id=None
            )
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
                        text="📄 В Google Doc",
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
```

Also import `LeadNotFoundError` at module top if not already imported (it lives in `qualify_lead.py`). Move `LeadNotFoundError` import to top:

```python
from crm.use_cases.qualify_lead import (
    LeadCannotQualifyError,
    LeadNotFoundError,
    qualify_lead,
)
```

(That's already there.) Just ensure `generate_proposal` imports are lazy inside the handler to avoid potential circular issues at module load — the lazy import shown above already does that.

### Step 2: Integration test for the propose callback

Create `tests/integration/test_bot_propose_callback.py`:

```python
"""Integration test: bot 'Сгенерировать предложение' callback runs generate_proposal."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import ChannelKind, LeadStatus, ProposalStatus
from crm.db.models.lead import Lead
from crm.entrypoints.bot import register_handlers


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
                date=dt.datetime.now(dt.UTC),
                chat=Chat(id=chat_id, type="private"),
                from_user=User(id=99, is_bot=True, first_name="bot"),
                text="prev",
            ),
        ),
    )


def _container_with_capturing_sender(settings: Settings) -> tuple[Container, list[dict]]:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]
    return container, sent


@pytest.mark.integration
async def test_bot_propose_callback_creates_proposal(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                summary="kitchen",
                extracted_data={"area_m2": 60},
                status=LeadStatus.qualified,
            )
        )
        await uow.commit()
        lead_id = lead.id

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = _make_callback_update(f"propose_lead:{lead_id}", user_id=operator_id)

    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(bot, update)

    assert len(sent) == 1
    assert "Proposal #" in sent[0]["text"]

    async with container.uow() as uow:
        proposals = await uow.proposals.list_by_lead(lead_id)
    assert len(proposals) == 1
    assert proposals[0].status == ProposalStatus.draft

    await container.aclose()
```

(Note: this test calls `uow.proposals.list_by_lead(lead_id)` — that method needs to exist. We add it in T2's wrap-up or here. Add it now if missing.)

### Step 3: Add `ProposalRepository.list_by_lead` if missing

Inspect `src/crm/db/repositories/proposals.py`. Confirm or add:

```python
async def list_by_lead(self, lead_id: int) -> Sequence[Proposal]:
    result = await self._session.execute(
        select(Proposal)
        .where(Proposal.lead_id == lead_id)
        .order_by(Proposal.version.asc(), Proposal.created_at.asc())
    )
    return result.scalars().all()
```

(Add the import of `Sequence` from `collections.abc` and `select` from `sqlalchemy` if not present.)

### Step 4: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_bot_propose_callback.py -v -m integration
```

Expected: 1 passed.

### Step 5: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **77 passed** (76 + 1).

### Step 6: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/entrypoints/bot.py src/crm/db/repositories/proposals.py tests/integration/test_bot_propose_callback.py
git commit -m "feat(bot): propose-lead callback runs generate_proposal"
```

---

## Task 4: `enqueue_job` helper + ScheduledJob repo extensions

**Files:**
- Create: `src/crm/scheduler/__init__.py`
- Create: `src/crm/scheduler/jobs.py`
- Modify: `src/crm/db/repositories/scheduled_jobs.py` (add `mark_done`, `reschedule`, `mark_failed_terminal`, `reclaim_stuck`)
- Create: `tests/unit/test_enqueue_job.py`
- Create: `tests/unit/test_scheduler_backoff.py`

### Step 1: Create `src/crm/scheduler/__init__.py`

```python
"""Postgres-backed job queue.

- ``jobs.enqueue_job(uow, ...)`` — atomic enqueue (idempotency-aware).
- ``jobs.apply_backoff(attempts)`` — exponential backoff with jitter.
- ``handlers.JOB_HANDLERS`` — registry of job_type → handler.
- ``runner.run_worker(container, worker_id)`` — main poll loop.
"""
```

### Step 2: Create `src/crm/scheduler/jobs.py`

```python
"""Job queue primitives — enqueue and backoff.

Spec §6.2. Encoded as plain functions; they take an open UoW and rely on
``uow.scheduled_jobs`` for persistence.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from crm.db.models.enums import JobStatus
from crm.db.models.scheduled_job import ScheduledJob

if TYPE_CHECKING:
    from crm.db.unit_of_work import SqlAlchemyUnitOfWork

log = structlog.get_logger(__name__)

# Worker lease — jobs locked longer than this are considered abandoned
# and reclaimed on the next poll tick. Tuned so a normal handler always
# finishes well under the lease.
LEASE_TIMEOUT: timedelta = timedelta(minutes=5)

# Base backoff: run_at = now + BASE * 2**attempts + jitter.
_BACKOFF_BASE: timedelta = timedelta(seconds=60)
_BACKOFF_JITTER_MAX: timedelta = timedelta(seconds=15)


async def enqueue_job(
    uow: SqlAlchemyUnitOfWork,
    *,
    job_type: str,
    payload: dict[str, Any],
    run_at: datetime | None = None,
    max_attempts: int = 5,
    idempotency_key: str | None = None,
) -> ScheduledJob:
    """Insert a row into ``scheduled_jobs`` inside the caller's UoW.

    If ``idempotency_key`` is provided and a job with this key already
    exists, returns the existing job WITHOUT inserting a duplicate.

    Does NOT commit. Use cases own the transaction boundary; this helper
    only stages the insert and flushes so ``job.id`` is populated.
    """
    if run_at is None:
        run_at = datetime.now(UTC)

    if idempotency_key is not None:
        existing = await uow.scheduled_jobs.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            log.info(
                "scheduler.enqueue_job.idempotency_hit",
                job_type=job_type,
                existing_job_id=existing.id,
                key=idempotency_key,
            )
            return existing

    job = await uow.scheduled_jobs.add(
        ScheduledJob(
            job_type=job_type,
            payload=payload,
            run_at=run_at,
            status=JobStatus.pending,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        )
    )
    log.info(
        "scheduler.enqueue_job.created",
        job_id=job.id,
        job_type=job_type,
        run_at=run_at.isoformat(),
    )
    return job


def apply_backoff(attempts: int, *, now: datetime | None = None) -> datetime:
    """Return the next ``run_at`` after ``attempts`` failed tries.

    Formula: ``now + BASE * 2**attempts + uniform(0, JITTER_MAX)``.
    """
    if now is None:
        now = datetime.now(UTC)
    multiplier = 2 ** max(0, attempts)
    jitter = timedelta(seconds=random.uniform(0, _BACKOFF_JITTER_MAX.total_seconds()))
    return now + _BACKOFF_BASE * multiplier + jitter
```

### Step 3: Extend `src/crm/db/repositories/scheduled_jobs.py`

Append three methods to `ScheduledJobRepository`:

```python
    async def mark_done(self, job_id: int, *, now: datetime) -> None:
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.done,
                locked_at=None,
                locked_by=None,
                last_error=None,
                updated_at=now,
            )
        )

    async def reschedule(
        self,
        job_id: int,
        *,
        run_at: datetime,
        last_error: str,
        now: datetime,
    ) -> None:
        """Mark a failed attempt and reschedule (status=pending, run_at later)."""
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.pending,
                run_at=run_at,
                last_error=last_error[:2000],
                locked_at=None,
                locked_by=None,
                updated_at=now,
            )
        )

    async def mark_failed_terminal(
        self, job_id: int, *, last_error: str, now: datetime
    ) -> None:
        """Job exhausted ``max_attempts`` — terminal failure."""
        await self._session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job_id)
            .values(
                status=JobStatus.failed,
                last_error=last_error[:2000],
                locked_at=None,
                locked_by=None,
                updated_at=now,
            )
        )

    async def reclaim_stuck(
        self, *, older_than: datetime, now: datetime
    ) -> int:
        """Return jobs locked-running before ``older_than`` to ``pending``.

        Returns the number of rows affected.
        """
        result = await self._session.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.status == JobStatus.running,
                ScheduledJob.locked_at < older_than,
            )
            .values(
                status=JobStatus.pending,
                locked_at=None,
                locked_by=None,
                updated_at=now,
            )
        )
        return result.rowcount or 0
```

### Step 4: Unit test `enqueue_job` (mocked uow)

Create `tests/unit/test_enqueue_job.py`:

```python
"""Unit tests for enqueue_job — idempotency and basic path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.scheduler.jobs import enqueue_job


@pytest.mark.asyncio
async def test_enqueue_job_inserts_new_when_no_key() -> None:
    uow = MagicMock()
    uow.scheduled_jobs = MagicMock()
    uow.scheduled_jobs.get_by_idempotency_key = AsyncMock(return_value=None)
    fake_job = MagicMock()
    fake_job.id = 1
    uow.scheduled_jobs.add = AsyncMock(return_value=fake_job)

    job = await enqueue_job(
        uow,
        job_type="test.job",
        payload={"x": 1},
    )

    assert job is fake_job
    uow.scheduled_jobs.get_by_idempotency_key.assert_not_called()
    uow.scheduled_jobs.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_job_returns_existing_on_idempotency_hit() -> None:
    existing = MagicMock()
    existing.id = 7
    uow = MagicMock()
    uow.scheduled_jobs = MagicMock()
    uow.scheduled_jobs.get_by_idempotency_key = AsyncMock(return_value=existing)
    uow.scheduled_jobs.add = AsyncMock()

    job = await enqueue_job(
        uow,
        job_type="test.job",
        payload={},
        idempotency_key="dup-key",
    )

    assert job is existing
    uow.scheduled_jobs.get_by_idempotency_key.assert_awaited_once_with("dup-key")
    uow.scheduled_jobs.add.assert_not_called()
```

### Step 5: Unit test backoff

Create `tests/unit/test_scheduler_backoff.py`:

```python
"""Unit tests for exponential backoff formula."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crm.scheduler.jobs import apply_backoff


def test_apply_backoff_grows_exponentially_with_attempts() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    delays = [apply_backoff(i, now=now) - now for i in range(5)]
    for prev, nxt in zip(delays, delays[1:], strict=False):
        assert nxt >= prev


def test_apply_backoff_uses_minute_base() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    d0 = apply_backoff(0, now=now) - now
    assert d0 >= timedelta(seconds=60)
    assert d0 <= timedelta(seconds=60 + 15)


def test_apply_backoff_attempts_3_is_around_eight_minutes() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    d3 = apply_backoff(3, now=now) - now
    assert d3 >= timedelta(minutes=8)
    assert d3 <= timedelta(minutes=8, seconds=15)
```

### Step 6: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_enqueue_job.py tests/unit/test_scheduler_backoff.py -v
```

Expected: 5 passed.

### Step 7: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **82 passed** (77 + 5).

### Step 8: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/scheduler/ src/crm/db/repositories/scheduled_jobs.py tests/unit/test_enqueue_job.py tests/unit/test_scheduler_backoff.py
git commit -m "feat(scheduler): enqueue_job + backoff + repo extensions (mark_done/reschedule/reclaim)"
```

---

## Task 5: Job handler registry + worker runner

**Files:**
- Create: `src/crm/scheduler/handlers.py`
- Create: `src/crm/scheduler/runner.py`
- Create: `tests/integration/test_worker_runner.py`

### Step 1: Create `src/crm/scheduler/handlers.py`

```python
"""Job-type → handler registry.

Handlers are plain async functions ``(container, job) -> None``. They run
inside the worker's per-job try/except: a raised exception triggers
reschedule (with backoff) or terminal failure.

A handler is free to open its OWN UoW for the real domain work — it
should NOT rely on the worker's job-control UoW.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.scheduled_job import ScheduledJob

JobHandler = Callable[["Container", "ScheduledJob"], Awaitable[None]]

JOB_HANDLERS: dict[str, JobHandler] = {}


def register_handler(job_type: str, handler: JobHandler) -> None:
    """Register a handler for ``job_type``.

    Idempotent — registering the same handler twice is a no-op; registering
    a *different* function under an already-claimed name raises.
    """
    if job_type in JOB_HANDLERS and JOB_HANDLERS[job_type] is not handler:
        raise RuntimeError(
            f"Job handler conflict: {job_type!r} already registered to "
            f"{JOB_HANDLERS[job_type]!r}, got {handler!r}"
        )
    JOB_HANDLERS[job_type] = handler


def get_handler(job_type: str) -> JobHandler | None:
    return JOB_HANDLERS.get(job_type)
```

### Step 2: Create `src/crm/scheduler/runner.py`

```python
"""Worker poll loop.

Picks pending jobs with FOR UPDATE SKIP LOCKED, marks them running, calls
the handler outside the picking transaction, and persists the outcome
(done / rescheduled with backoff / terminally failed) in a separate
transaction.

Concurrency: multiple workers can run safely thanks to
``FOR UPDATE SKIP LOCKED``. Lease timeout (5 min) reclaims jobs left
behind by crashed workers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from crm.scheduler.handlers import get_handler
from crm.scheduler.jobs import LEASE_TIMEOUT, apply_backoff

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.scheduled_job import ScheduledJob

log = structlog.get_logger(__name__)


async def run_worker(
    container: Container,
    *,
    worker_id: str,
    shutdown: asyncio.Event,
) -> None:
    """Run the worker until ``shutdown`` is set.

    Each tick:
      1. Reclaim jobs whose lease expired (locked_at older than LEASE_TIMEOUT).
      2. Pick up to 10 due pending jobs (FOR UPDATE SKIP LOCKED), mark them
         running, commit the picking TX.
      3. For each picked job, run its handler outside the picking TX. The
         handler raises on failure.
      4. After the handler returns/raises, in a fresh TX mark the job done,
         or reschedule (with backoff) if attempts < max_attempts, or mark
         it failed terminally.

    On terminal failure, notify the first allowlisted operator on Telegram
    so the alert isn't silent (spec §6.7).
    """
    poll_interval = container.settings.worker_poll_interval_seconds
    log.info(
        "worker.starting",
        worker_id=worker_id,
        poll_interval_seconds=poll_interval,
    )

    while not shutdown.is_set():
        try:
            await _reclaim(container)
            picked = await _pick_due_jobs(container, worker_id=worker_id, limit=10)
            for job in picked:
                await _run_one(container, job)
        except Exception as exc:
            log.exception(
                "worker.tick.error",
                worker_id=worker_id,
                error=str(exc),
            )

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
        except TimeoutError:
            continue

    log.info("worker.stopped", worker_id=worker_id)


async def _reclaim(container: Container) -> None:
    now = datetime.now(UTC)
    cutoff = now - LEASE_TIMEOUT
    async with container.uow() as uow:
        rows = await uow.scheduled_jobs.reclaim_stuck(older_than=cutoff, now=now)
        await uow.commit()
    if rows:
        log.warning("worker.reclaimed", count=rows)


async def _pick_due_jobs(
    container: Container, *, worker_id: str, limit: int
) -> list["ScheduledJob"]:
    now = datetime.now(UTC)
    async with container.uow() as uow:
        jobs = list(await uow.scheduled_jobs.list_pending_due(now=now, limit=limit))
        for job in jobs:
            await uow.scheduled_jobs.mark_running(
                job.id, worker_id=worker_id, now=now
            )
            job.attempts += 1  # mirror the DB-side increment locally
        await uow.commit()
    return jobs


async def _run_one(container: Container, job: "ScheduledJob") -> None:
    handler = get_handler(job.job_type)
    if handler is None:
        await _finalize_terminal(
            container, job, error=f"no handler registered for {job.job_type!r}"
        )
        return

    try:
        await handler(container, job)
    except Exception as exc:
        log.warning(
            "worker.handler.failed",
            job_id=job.id,
            job_type=job.job_type,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error=str(exc),
        )
        if job.attempts >= job.max_attempts:
            await _finalize_terminal(container, job, error=str(exc))
        else:
            await _finalize_reschedule(container, job, error=str(exc))
        return

    await _finalize_done(container, job)


async def _finalize_done(container: Container, job: "ScheduledJob") -> None:
    now = datetime.now(UTC)
    async with container.uow() as uow:
        await uow.scheduled_jobs.mark_done(job.id, now=now)
        await uow.commit()
    log.info("worker.handler.done", job_id=job.id, job_type=job.job_type)


async def _finalize_reschedule(
    container: Container, job: "ScheduledJob", *, error: str
) -> None:
    now = datetime.now(UTC)
    next_run = apply_backoff(job.attempts, now=now)
    async with container.uow() as uow:
        await uow.scheduled_jobs.reschedule(
            job.id, run_at=next_run, last_error=error, now=now
        )
        await uow.commit()
    log.info(
        "worker.handler.rescheduled",
        job_id=job.id,
        next_run_at=next_run.isoformat(),
        attempts=job.attempts,
    )


async def _finalize_terminal(
    container: Container, job: "ScheduledJob", *, error: str
) -> None:
    now = datetime.now(UTC)
    async with container.uow() as uow:
        await uow.scheduled_jobs.mark_failed_terminal(
            job.id, last_error=error, now=now
        )
        await uow.commit()
    log.error(
        "worker.handler.failed_terminal",
        job_id=job.id,
        job_type=job.job_type,
        error=error,
    )
    await _notify_operator_about_failure(container, job, error)


async def _notify_operator_about_failure(
    container: Container, job: "ScheduledJob", error: str
) -> None:
    ids = container.settings.telegram_operator_ids
    if not ids:
        return
    chat_id = ids[0]
    try:
        await container.telegram_sender.send_message(
            chat_id=chat_id,
            text=(
                f"⚠ Job {job.id} ({job.job_type}) сдох окончательно "
                f"после {job.attempts} попыток.\nОшибка: {error[:500]}"
            ),
        )
    except Exception as exc:
        log.warning(
            "worker.alert.failed",
            job_id=job.id,
            error=str(exc),
        )
```

### Step 3: Integration test for the worker runner

Create `tests/integration/test_worker_runner.py`:

```python
"""Integration tests for the worker poll loop (end-to-end)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import JobStatus
from crm.db.models.scheduled_job import ScheduledJob
from crm.scheduler.handlers import JOB_HANDLERS, register_handler
from crm.scheduler.runner import _pick_due_jobs, _run_one, run_worker


@pytest.fixture(autouse=True)
def _clean_handlers():
    JOB_HANDLERS.clear()
    yield
    JOB_HANDLERS.clear()


@pytest.mark.integration
async def test_worker_picks_due_job_and_marks_done(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    called: list[int] = []

    async def _handler(c: Container, job: ScheduledJob) -> None:
        called.append(job.id)

    register_handler("test.success", _handler)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="test.success",
                payload={"x": 1},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=5,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    assert picked[0].id == job_id
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.done
    assert called == [job_id]

    await container.aclose()


@pytest.mark.integration
async def test_worker_reschedules_on_handler_exception(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)

    async def _broken(c: Container, job: ScheduledJob) -> None:
        raise RuntimeError("boom")

    register_handler("test.broken", _broken)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="test.broken",
                payload={},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=3,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.pending  # rescheduled
    assert reloaded.attempts == 1
    assert reloaded.last_error == "boom"
    assert reloaded.run_at > datetime.now(UTC)

    await container.aclose()


@pytest.mark.integration
async def test_worker_marks_failed_terminal_after_max_attempts(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    from unittest.mock import MagicMock

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

    async def _broken(c: Container, job: ScheduledJob) -> None:
        raise RuntimeError("permanent")

    register_handler("test.broken", _broken)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="test.broken",
                payload={},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                attempts=2,  # mark_running will bump to 3
                max_attempts=3,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.failed
    assert reloaded.last_error == "permanent"
    assert len(sent) == 1
    assert "сдох" in sent[0]["text"]

    await container.aclose()


@pytest.mark.integration
async def test_worker_unknown_job_type_marks_failed(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)

    async with container.uow() as uow:
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="nope.unknown",
                payload={},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=3,
            )
        )
        await uow.commit()
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded = await uow.scheduled_jobs.get(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.failed
    assert "no handler" in (reloaded.last_error or "")

    await container.aclose()


@pytest.mark.integration
async def test_run_worker_stops_on_shutdown_event(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    shutdown = asyncio.Event()
    settings.worker_poll_interval_seconds = 0.05  # type: ignore[misc]

    async def _stopper():
        await asyncio.sleep(0.2)
        shutdown.set()

    await asyncio.gather(
        run_worker(container, worker_id="t1", shutdown=shutdown),
        _stopper(),
    )

    await container.aclose()
```

### Step 4: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_worker_runner.py -v -m integration
```

Expected: 5 passed.

### Step 5: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **87 passed** (82 + 5).

### Step 6: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/scheduler/handlers.py src/crm/scheduler/runner.py tests/integration/test_worker_runner.py
git commit -m "feat(scheduler): handler registry + run_worker poll loop with reclaim/backoff"
```

---

## Task 6: Worker entrypoint script

**Files:**
- Modify: `src/crm/entrypoints/worker.py`

### Step 1: Read existing `src/crm/entrypoints/worker.py`

Plan 1 stub. Replace its body with a real entrypoint.

### Step 2: Replace contents

```python
"""Worker entrypoint — scheduled_jobs poll loop.

Single process that:
  1. Builds a Container.
  2. Registers handlers from all known modules.
  3. Runs the poll loop until SIGTERM / SIGINT.
"""

from __future__ import annotations

import asyncio
import signal
import socket
import uuid

import structlog

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging
from crm.scheduler.runner import run_worker

log = structlog.get_logger(__name__)


def _register_all_handlers() -> None:
    """Centralised handler registration.

    Add new ``register_handler(...)`` calls here as job types are
    introduced. Lazy imports keep test-only modules out of the runtime
    dependency graph.
    """
    from crm.scheduler.handlers import register_handler
    from crm.use_cases.publish_proposal_to_gdoc import (
        JOB_TYPE_PUBLISH_PROPOSAL,
        handle_publish_proposal_to_gdoc,
    )

    register_handler(JOB_TYPE_PUBLISH_PROPOSAL, handle_publish_proposal_to_gdoc)


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)

    _register_all_handlers()

    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, sig_name), shutdown.set)
        except (NotImplementedError, AttributeError):
            # Windows / unsupported platforms — ignore; CTRL-C still raises.
            pass

    try:
        await run_worker(container, worker_id=worker_id, shutdown=shutdown)
    finally:
        await container.aclose()
        log.info("worker.entrypoint.stopped", worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(run())
```

(Note: `publish_proposal_to_gdoc` module and `JOB_TYPE_PUBLISH_PROPOSAL` constant + `handle_publish_proposal_to_gdoc` callable arrive in Task 7 + 8. Importing them here works only because the `_register_all_handlers` function is called LAZILY at runtime, AFTER those tasks land. To keep T6 self-contained, comment those lines out during T6 and uncomment in T8.)

**Workaround for T6 in isolation:** wrap the import in a try/except so T6's test (and the worker entrypoint) doesn't fail before T7/T8 lands.

Use this for the registration step:

```python
def _register_all_handlers() -> None:
    """Centralised handler registration."""
    from crm.scheduler.handlers import register_handler

    try:
        from crm.use_cases.publish_proposal_to_gdoc import (
            JOB_TYPE_PUBLISH_PROPOSAL,
            handle_publish_proposal_to_gdoc,
        )
    except ImportError:
        # Will be filled in once T7/T8 land. Leaving this here so T6's
        # entrypoint smoke-test passes before publish_proposal_to_gdoc exists.
        return

    register_handler(JOB_TYPE_PUBLISH_PROPOSAL, handle_publish_proposal_to_gdoc)
```

### Step 3: Smoke import test (unit)

No new file — verify the entrypoint module imports cleanly:

```
& "$env:USERPROFILE\.local\bin\uv.exe" run python -c "import crm.entrypoints.worker; print('ok')"
```

Expected: `ok`.

### Step 4: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **87 passed** (no new tests in T6).

### Step 5: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/entrypoints/worker.py
git commit -m "feat(worker): entrypoint with signal-based shutdown and handler registration"
```

---

## Task 7: `publish_proposal_to_gdoc` use case (enqueue-only)

**Files:**
- Create: `src/crm/use_cases/publish_proposal_to_gdoc.py` (use case + handler — co-located in one module so they share the same `JOB_TYPE_*` constant)
- Modify: `src/crm/db/repositories/documents.py` (add `list_by_owner`)
- Create: `tests/unit/test_publish_proposal_to_gdoc_unit.py`
- Create: `tests/integration/test_publish_proposal_to_gdoc.py`

This task implements only the **use case** (enqueue + event). The actual job **handler** body comes in Task 8 — but we'll co-locate them in the same module for clarity, with the handler being a placeholder in T7 that's filled in T8. Alternatively, ship both in one task — choose based on size. Below is the combined version (T7+T8 in one file, executed across two tasks for review cadence).

### Step 1: Write integration test for the enqueue path

Create `tests/integration/test_publish_proposal_to_gdoc.py`:

```python
"""Integration tests for publish_proposal_to_gdoc use case (enqueue only)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.use_cases.publish_proposal_to_gdoc import (
    JOB_TYPE_PUBLISH_PROPOSAL,
    ProposalNotReadyError,
    ProposalNotFoundError,
    publish_proposal_to_gdoc,
)


async def _seed_proposal(container: Container, *, status: ProposalStatus, with_body: bool = True) -> int:
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(channel=ChannelKind.telegram, raw_text="r", status=LeadStatus.qualified)
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=status,
                generated_text="proposal body" if with_body else "",
                scope_summary="scope",
                currency="RUB",
            )
        )
        await uow.commit()
        return proposal.id


@pytest.mark.integration
async def test_publish_proposal_enqueues_job(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    proposal_id = await _seed_proposal(container, status=ProposalStatus.draft)

    job = await publish_proposal_to_gdoc(
        container, proposal_id=proposal_id, operator_user_id=None
    )

    assert job.job_type == JOB_TYPE_PUBLISH_PROPOSAL
    assert job.status == JobStatus.pending
    assert job.payload["proposal_id"] == proposal_id
    assert job.idempotency_key == f"publish_proposal_to_gdoc:{proposal_id}"

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("proposal", proposal_id)
    types = [e.event_type for e in events]
    assert "proposal.publish_requested" in types

    await container.aclose()


@pytest.mark.integration
async def test_publish_proposal_is_idempotent(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    proposal_id = await _seed_proposal(container, status=ProposalStatus.draft)

    job1 = await publish_proposal_to_gdoc(
        container, proposal_id=proposal_id, operator_user_id=None
    )
    job2 = await publish_proposal_to_gdoc(
        container, proposal_id=proposal_id, operator_user_id=None
    )

    assert job1.id == job2.id  # same row returned

    await container.aclose()


@pytest.mark.integration
async def test_publish_proposal_rejects_empty_body(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    proposal_id = await _seed_proposal(
        container, status=ProposalStatus.draft, with_body=False
    )

    with pytest.raises(ProposalNotReadyError):
        await publish_proposal_to_gdoc(
            container, proposal_id=proposal_id, operator_user_id=None
        )

    await container.aclose()


@pytest.mark.integration
async def test_publish_proposal_missing_raises(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    with pytest.raises(ProposalNotFoundError):
        await publish_proposal_to_gdoc(
            container, proposal_id=999_999, operator_user_id=None
        )
    await container.aclose()
```

### Step 2: Create `src/crm/use_cases/publish_proposal_to_gdoc.py` (use case only — handler in T8)

```python
"""publish_proposal_to_gdoc — enqueue a worker job to publish a proposal.

Spec §5.1 steps 12-18. Fast use case: just enqueues a job with an
idempotency key so spamming the button doesn't create duplicates. The
worker handler (see ``handle_publish_proposal_to_gdoc``, T8) does the
heavy lifting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from crm.db.models.scheduled_job import ScheduledJob
from crm.scheduler.jobs import enqueue_job
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.proposal import Proposal

log = structlog.get_logger(__name__)

JOB_TYPE_PUBLISH_PROPOSAL = "publish_proposal_to_gdoc"


class ProposalNotFoundError(LookupError):
    """No proposal with the requested id."""


class ProposalNotReadyError(ValueError):
    """Proposal has no generated body — cannot publish."""


async def publish_proposal_to_gdoc(
    container: Container,
    *,
    proposal_id: int,
    operator_user_id: int | None,
) -> ScheduledJob:
    """Enqueue a job to publish ``proposal`` into Google Docs.

    Idempotent — repeated calls with the same proposal_id return the
    existing pending job.

    Raises:
        ProposalNotFoundError
        ProposalNotReadyError: when ``generated_text`` is empty.
    """
    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
        if not (proposal.generated_text or "").strip():
            raise ProposalNotReadyError(
                f"Proposal {proposal_id} has no body — generate it first"
            )

        job = await enqueue_job(
            uow,
            job_type=JOB_TYPE_PUBLISH_PROPOSAL,
            payload={"proposal_id": proposal_id},
            idempotency_key=f"publish_proposal_to_gdoc:{proposal_id}",
            max_attempts=5,
        )

        await record_event(
            uow,
            event_type="proposal.publish_requested",
            aggregate_type="proposal",
            aggregate_id=proposal_id,
            payload={"job_id": job.id},
            actor_user_id=operator_user_id,
        )

        await uow.commit()
        result_job = job

    log.info(
        "publish_proposal_to_gdoc.enqueued",
        proposal_id=proposal_id,
        job_id=result_job.id,
    )
    return result_job


# `handle_publish_proposal_to_gdoc` lives below — implemented in Task 8.
# Stub left so T6's worker entrypoint can import the symbol.

async def handle_publish_proposal_to_gdoc(
    container: Container, job: ScheduledJob
) -> None:
    """Stub — see Task 8."""
    raise NotImplementedError("handle_publish_proposal_to_gdoc — implemented in T8")
```

### Step 3: Lightweight unit test

Create `tests/unit/test_publish_proposal_to_gdoc_unit.py`:

```python
"""Unit tests for publish_proposal_to_gdoc — error paths without DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.use_cases.publish_proposal_to_gdoc import (
    ProposalNotFoundError,
    ProposalNotReadyError,
    publish_proposal_to_gdoc,
)


@pytest.mark.asyncio
async def test_publish_raises_when_proposal_missing() -> None:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.proposals = MagicMock()
    uow.proposals.get = AsyncMock(return_value=None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(ProposalNotFoundError):
        await publish_proposal_to_gdoc(
            container, proposal_id=1, operator_user_id=None
        )


@pytest.mark.asyncio
async def test_publish_raises_when_body_empty() -> None:
    proposal = MagicMock()
    proposal.id = 1
    proposal.generated_text = "   "
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.proposals = MagicMock()
    uow.proposals.get = AsyncMock(return_value=proposal)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(ProposalNotReadyError):
        await publish_proposal_to_gdoc(
            container, proposal_id=1, operator_user_id=None
        )
```

### Step 4: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_publish_proposal_to_gdoc_unit.py tests/integration/test_publish_proposal_to_gdoc.py -v
```

Expected: 2 unit + 4 integration = 6 passed.

### Step 5: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **93 passed** (87 + 6).

### Step 6: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/use_cases/publish_proposal_to_gdoc.py tests/unit/test_publish_proposal_to_gdoc_unit.py tests/integration/test_publish_proposal_to_gdoc.py
git commit -m "feat(use_cases): publish_proposal_to_gdoc enqueues idempotent worker job"
```

---

## Task 8: GDocs job handler — actually create the Doc and notify operator

**Files:**
- Modify: `src/crm/use_cases/publish_proposal_to_gdoc.py` (replace stub `handle_publish_proposal_to_gdoc`)
- Modify: `src/crm/db/repositories/documents.py` (add `list_by_owner`)
- Create: `tests/integration/test_worker_publish_gdoc.py`

### Step 1: Extend `DocumentRepository`

Append to `src/crm/db/repositories/documents.py`:

```python
    async def list_by_owner(
        self, owner_type: DocumentOwnerType, owner_id: int
    ) -> Sequence[Document]:
        result = await self._session.execute(
            select(Document)
            .where(
                Document.owner_type == owner_type,
                Document.owner_id == owner_id,
            )
            .order_by(Document.created_at.asc())
        )
        return result.scalars().all()
```

(Imports: `from collections.abc import Sequence`, `from sqlalchemy import select`. Verify both are present; add if missing.)

### Step 2: Replace the stub handler

In `src/crm/use_cases/publish_proposal_to_gdoc.py`, replace the `handle_publish_proposal_to_gdoc` stub with:

```python
async def handle_publish_proposal_to_gdoc(
    container: Container, job: ScheduledJob
) -> None:
    """Worker handler: create a Google Doc for the proposal.

    Steps:
      1. Read proposal (and check whether a Document already exists for
         idempotency on retries).
      2. Outside any transaction, call ``gdocs.create_doc(...)``.
      3. INSERT Document; record ``proposal.published_to_gdoc`` event.
      4. Notify the first allowlisted operator with the resulting URL.

    Idempotency: if a Document with ``owner_type='proposal'`` and
    ``kind='gdoc'`` already exists for this proposal, we skip the
    external call and treat the job as done. This handles the case
    where the previous worker crashed between gdocs.create_doc() and
    the Document INSERT, leaving an orphan Google Doc — we accept the
    orphan and move on.
    """
    from crm.db.models.document import Document
    from crm.db.models.enums import DocumentKind, DocumentOwnerType

    proposal_id = int(job.payload["proposal_id"])

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise RuntimeError(
                f"handle_publish_proposal_to_gdoc: Proposal {proposal_id} not found"
            )

        existing = await uow.documents.list_by_owner(
            DocumentOwnerType.proposal, proposal_id
        )
        already_gdoc = next(
            (d for d in existing if d.kind == DocumentKind.gdoc), None
        )
        body = proposal.generated_text or ""
        scope = proposal.scope_summary or ""
        lead_id = proposal.lead_id

    if already_gdoc is not None:
        log.info(
            "handle_publish_proposal_to_gdoc.idempotency_hit",
            proposal_id=proposal_id,
            document_id=already_gdoc.id,
        )
        await _send_operator_link(container, proposal_id, already_gdoc.url or "(no url)")
        return

    title = f"Proposal #{proposal_id} (lead #{lead_id}) — {scope[:60]}"
    ref = await container.gdocs.create_doc(title=title, body=body)

    async with container.uow() as uow:
        doc = await uow.documents.add(
            Document(
                owner_type=DocumentOwnerType.proposal,
                owner_id=proposal_id,
                kind=DocumentKind.gdoc,
                title=ref.title,
                url=ref.url,
                gdoc_id=ref.doc_id,
                mime_type="application/vnd.google-apps.document",
                uploaded_by_user_id=None,
            )
        )
        await record_event(
            uow,
            event_type="proposal.published_to_gdoc",
            aggregate_type="proposal",
            aggregate_id=proposal_id,
            payload={
                "document_id": doc.id,
                "gdoc_id": ref.doc_id,
                "url": ref.url,
            },
            actor_user_id=None,
        )
        await uow.commit()

    await _send_operator_link(container, proposal_id, ref.url)
    log.info(
        "handle_publish_proposal_to_gdoc.done",
        proposal_id=proposal_id,
        gdoc_id=ref.doc_id,
    )


async def _send_operator_link(
    container: Container, proposal_id: int, url: str
) -> None:
    ids = container.settings.telegram_operator_ids
    if not ids:
        return
    chat_id = ids[0]
    try:
        await container.telegram_sender.send_message(
            chat_id=chat_id,
            text=f"📄 Proposal #{proposal_id} опубликован: {url}",
        )
    except Exception as exc:
        log.warning(
            "handle_publish_proposal_to_gdoc.notify_failed",
            proposal_id=proposal_id,
            error=str(exc),
        )
```

Add at the top of the file (extending imports):

```python
from crm.use_cases.events import record_event  # already present
```

### Step 3: Register handler in the worker entrypoint

Open `src/crm/entrypoints/worker.py` and **remove the try/except wrapper** around the import (introduced in T6) so the registration always happens:

```python
def _register_all_handlers() -> None:
    from crm.scheduler.handlers import register_handler
    from crm.use_cases.publish_proposal_to_gdoc import (
        JOB_TYPE_PUBLISH_PROPOSAL,
        handle_publish_proposal_to_gdoc,
    )

    register_handler(JOB_TYPE_PUBLISH_PROPOSAL, handle_publish_proposal_to_gdoc)
```

### Step 4: End-to-end integration test

Create `tests/integration/test_worker_publish_gdoc.py`:

```python
"""End-to-end: enqueue publish_proposal_to_gdoc → worker picks → Document + Telegram."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    DocumentKind,
    DocumentOwnerType,
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.scheduler.handlers import JOB_HANDLERS, register_handler
from crm.scheduler.runner import _pick_due_jobs, _run_one
from crm.use_cases.publish_proposal_to_gdoc import (
    JOB_TYPE_PUBLISH_PROPOSAL,
    handle_publish_proposal_to_gdoc,
    publish_proposal_to_gdoc,
)


@pytest.fixture(autouse=True)
def _wire_handler():
    JOB_HANDLERS.clear()
    register_handler(JOB_TYPE_PUBLISH_PROPOSAL, handle_publish_proposal_to_gdoc)
    yield
    JOB_HANDLERS.clear()


async def _seed_proposal(container: Container) -> int:
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(channel=ChannelKind.telegram, raw_text="r", status=LeadStatus.qualified)
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.draft,
                generated_text="body of the proposal",
                scope_summary="kitchen",
                currency="RUB",
            )
        )
        await uow.commit()
        return proposal.id


@pytest.mark.integration
async def test_worker_publishes_proposal_to_gdoc_end_to_end(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

    proposal_id = await _seed_proposal(container)
    await publish_proposal_to_gdoc(
        container, proposal_id=proposal_id, operator_user_id=None
    )

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    await _run_one(container, picked[0])

    # Assertions
    async with container.uow() as uow:
        docs = await uow.documents.list_by_owner(
            DocumentOwnerType.proposal, proposal_id
        )
        events = await uow.events.list_for_aggregate("proposal", proposal_id)
        reloaded_job = await uow.scheduled_jobs.get(picked[0].id)

    assert len(docs) == 1
    assert docs[0].kind == DocumentKind.gdoc
    assert docs[0].url.startswith("https://docs.example.com/")
    assert docs[0].gdoc_id.startswith("fake-")

    types = [e.event_type for e in events]
    assert "proposal.publish_requested" in types
    assert "proposal.published_to_gdoc" in types

    assert reloaded_job is not None
    assert reloaded_job.status == JobStatus.done

    assert len(sent) == 1
    assert "опубликован" in sent[0]["text"]
    assert "https://docs.example.com/" in sent[0]["text"]

    await container.aclose()


@pytest.mark.integration
async def test_worker_gdocs_handler_is_idempotent_on_retry(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    """Simulate: handler ran once, then ran AGAIN after a retry — no duplicate Doc."""
    container = Container(settings)

    proposal_id = await _seed_proposal(container)
    await publish_proposal_to_gdoc(
        container, proposal_id=proposal_id, operator_user_id=None
    )

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    job = picked[0]
    # Run handler twice (simulating retry / replay).
    await handle_publish_proposal_to_gdoc(container, job)
    await handle_publish_proposal_to_gdoc(container, job)

    async with container.uow() as uow:
        docs = await uow.documents.list_by_owner(
            DocumentOwnerType.proposal, proposal_id
        )
    assert len(docs) == 1  # single document despite two handler invocations

    # FakeGDocsClient.created records ONE create — verify we didn't hit it twice.
    assert len(container.gdocs.created) == 1

    await container.aclose()
```

### Step 5: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_worker_publish_gdoc.py -v -m integration
```

Expected: 2 passed.

### Step 6: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **95 passed** (93 + 2).

### Step 7: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/use_cases/publish_proposal_to_gdoc.py src/crm/db/repositories/documents.py src/crm/entrypoints/worker.py tests/integration/test_worker_publish_gdoc.py
git commit -m "feat(scheduler): GDocs job handler creates Document, notifies operator"
```

---

## Task 9: Bot button — "В Google Doc"

**Files:**
- Modify: `src/crm/entrypoints/bot.py` (add `PUBLISH_PROPOSAL_PREFIX` handler)
- Create: `tests/integration/test_bot_publish_callback.py`

The propose-button reply (from T3) already renders a `publish_proposal:{id}` button. T9 wires the callback handler.

### Step 1: Add constants + handler to `src/crm/entrypoints/bot.py`

Add near other prefixes:

```python
PUBLISH_PROPOSAL_PREFIX = "publish_proposal:"
```

Add the handler after `on_propose`:

```python
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
```

### Step 2: Integration test

Create `tests/integration/test_bot_publish_callback.py`:

```python
"""Integration test: bot 'В Google Doc' callback enqueues the publish job."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.entrypoints.bot import register_handlers


def _container_with_capturing_sender(settings: Settings) -> tuple[Container, list[dict]]:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]
    return container, sent


@pytest.mark.integration
async def test_bot_publish_callback_enqueues_job(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container, sent = _container_with_capturing_sender(settings)

    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(channel=ChannelKind.telegram, raw_text="r", status=LeadStatus.qualified)
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.draft,
                generated_text="body",
                scope_summary="scope",
                currency="RUB",
            )
        )
        await uow.commit()
        proposal_id = proposal.id

    dp = Dispatcher()
    register_handlers(dp, container)

    operator_id = next(iter(settings.telegram_operator_ids))
    update = Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=operator_id, is_bot=False, first_name="Op"),
            chat_instance="ci-1",
            data=f"publish_proposal:{proposal_id}",
            message=Message(
                message_id=1002,
                date=dt.datetime.now(dt.UTC),
                chat=Chat(id=100, type="private"),
                from_user=User(id=99, is_bot=True, first_name="bot"),
                text="prev",
            ),
        ),
    )

    bot = AsyncMock()
    bot.id = 99
    await dp.feed_update(bot, update)

    assert len(sent) == 1
    assert "Запросил публикацию" in sent[0]["text"]

    async with container.uow() as uow:
        async with container.session_factory() as session:
            from sqlalchemy import select

            from crm.db.models.scheduled_job import ScheduledJob

            result = await session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.job_type == "publish_proposal_to_gdoc"
                )
            )
            jobs = list(result.scalars().all())
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.pending
    assert jobs[0].payload["proposal_id"] == proposal_id

    await container.aclose()
```

### Step 3: Run tests

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/integration/test_bot_publish_callback.py -v -m integration
```

Expected: 1 passed.

### Step 4: Full suite

```
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: **96 passed** (95 + 1).

### Step 5: Ruff + commit

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format .

git add src/crm/entrypoints/bot.py tests/integration/test_bot_publish_callback.py
git commit -m "feat(bot): publish_proposal callback enqueues the worker job"
```

---

## Task 10: README + tag

**Files:**
- Modify: `README.md`
- Tag: `plan-5a-proposal-and-worker`

### Step 1: Update README status

Change:

```markdown
- [x] Plan 4: AI Adapters (OpenAI)
- [ ] Plan 5: Proposal + Scheduler + Worker
```

to:

```markdown
- [x] Plan 4: AI Adapters (OpenAI)
- [x] Plan 5a: Proposal Generation + Worker + GDocs Publishing
- [ ] Plan 5b: mark_proposal_sent + FollowUp + send_follow_up
```

In "Architecture in 30 seconds", append below the AI adapters block:

```
worker (Plan 5a):
  scheduled_jobs queue (Postgres, FOR UPDATE SKIP LOCKED, exp backoff)
  handler registry — register job_type → callable
  current handlers: publish_proposal_to_gdoc

use cases added in Plan 5a:
  generate_proposal     publish_proposal_to_gdoc
```

In the layout block, add:

```
  scheduler/            # job queue: enqueue_job, backoff, runner, handlers
```

### Step 2: Final verification

```
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format --check .
& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v
```

Expected: 96 passed, ruff green.

### Step 3: Commit + tag

```
git add README.md
git commit -m "docs(domain): README — Plan 5a complete (proposal generation + worker + GDocs)"

git tag -a plan-5a-proposal-and-worker -m "Plan 5a: Proposal Generation + Worker Infrastructure + GDocs Publishing"
git log --oneline -5
git tag --list "plan-*"
```

Expected: new tag in the list.

---

## Self-Review checklist

**Spec coverage:**

| Spec section | Tasks |
|---|---|
| §5.1 steps 8-11 (generate_proposal) | Task 2 |
| §5.1 step 12 (bot button) | Task 3 |
| §5.1 step 13 (publish use case) | Task 7 |
| §5.1 steps 14-15 (enqueue + worker pick) | Tasks 4, 5, 7 |
| §5.1 step 16 (gdocs.create_doc) | Task 8 |
| §5.1 step 17 (Document INSERT + event) | Task 8 |
| §5.1 step 18 (operator notification) | Task 8 |
| §5.2 use case contracts (UoW, AI outside TX) | Tasks 2, 7 |
| §5.4 retry/backoff for worker | Tasks 4, 5 |
| §5.4 reclaim-on-crash | Task 5 |
| §5.4 idempotency (Document existence check) | Task 8 |
| §6.2 enqueue() signature | Task 4 |
| §6.2 worker loop pseudocode | Task 5 |
| §6.7 alert on terminal failure | Task 5 |
| §11 prompts in `prompts/` as `.j2` | already (Plan 3+4) |

**Test isolation backlog item:** addressed in Task 1.

---

## Definition of Done

- [ ] `uv run pytest -v` is green; expected count ≈ 96.
- [ ] `uv run ruff check .` and `ruff format --check .` are green.
- [ ] Tag `plan-5a-proposal-and-worker` exists at end of T10.
- [ ] `generate_proposal` works end-to-end with `AI_PROVIDER=fake`.
- [ ] Bot button "📝 Сгенерировать предложение" appears after qualify and triggers `generate_proposal`.
- [ ] Bot button "📄 В Google Doc" enqueues a job; worker picks it; Document row appears; operator gets notified.
- [ ] `db_clean` fixture used by all stateful integration tests; no inline cleanup helpers remain.

---

## Backlog for Plan 5b / later

- `mark_proposal_sent` + FollowUp scheduling.
- `send_follow_up` worker handler.
- `record_follow_up_result` use case.
- Real Google service-account GDocs adapter (Plan 6 originally).
- Bot "Edit proposal" callback (placeholder).
- Worker prometheus metrics (oldest_pending_age, jobs/sec).
- Replace polymorphic `documents.owner_type/id` lookup helper with a more typed API once we touch it heavily.

---

## Execution handoff

**Plan complete and saved. Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task with combined spec+quality review between tasks. Worked well for Plan 1, 2, 3+4.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans` with checkpoints after T1 (test isolation), T5 (worker infra), and T8 (GDocs handler).

**Which approach?**
