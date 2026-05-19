# Reyzbikh Buro CRM

CRM/workflow platform for an architecture bureau. Postgres-centered; Telegram is one input channel of many planned.

> **Design spec:** [`docs/superpowers/specs/2026-05-19-crm-platform-design.md`](docs/superpowers/specs/2026-05-19-crm-platform-design.md)
> **Implementation plans:** [`docs/superpowers/plans/`](docs/superpowers/plans/)

## Status

- [x] Plan 1: Foundation
- [x] Plan 2: Domain + Schema
- [ ] Plan 3: Lead Intake (fake AI)
- [ ] Plan 4: AI Adapters
- [ ] Plan 5: Proposal + Scheduler + Worker
- [ ] Plan 6: Google Docs adapter
- [ ] Plan 7: Follow-ups
- [ ] Plan 8: Production hardening

## Architecture in 30 seconds

```
docker compose:
  postgres   — pg 16 alpine
  migrate    — one-shot: alembic upgrade head
  api        — FastAPI :8000 (so far: /healthz)
  bot        — aiogram long-polling
  worker     — scheduler/jobs loop

domain tables (Plan 2):
  users  clients  leads  projects  proposals
  follow_ups  contracts  documents
  events  scheduled_jobs
```

All three Python processes share the `crm` package. Business logic will live in `src/crm/use_cases/`. Adapters (AI, GDocs, Telegram outbound) sit behind `Protocol` interfaces with `Fake*` impls for tests and early dev. Repositories live in `src/crm/db/repositories/`; access via `uow.leads`, `uow.proposals`, etc.

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
  db/
    base.py             # SQLAlchemy declarative Base
    session.py          # async engine + session factory
    unit_of_work.py     # SqlAlchemyUnitOfWork + uow_scope
    models/             # ORM models (one file per entity)
    repositories/       # async repos hung off UoW
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
