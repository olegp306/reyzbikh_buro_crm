"""Integration tests for repositories.

Each test creates a Container, runs Alembic upgrade head against a fresh
testcontainer Postgres, then exercises one repository at a time inside a UoW.
"""

from __future__ import annotations

import asyncio
from datetime import UTC

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.client import Client
from crm.db.models.enums import ClientSource, LeadStatus, UserRole
from crm.db.models.lead import Lead
from crm.db.models.user import User


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
async def test_user_repository_crud_round_trip(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        u = await uow.users.add(
            User(telegram_id=12345, display_name="Operator One", role=UserRole.owner)
        )
        await uow.commit()
        user_id = u.id

    async with container.uow() as uow:
        loaded = await uow.users.get(user_id)
        assert loaded is not None
        assert loaded.display_name == "Operator One"
        by_tg = await uow.users.get_by_telegram_id(12345)
        assert by_tg is not None and by_tg.id == user_id

    await container.aclose()


@pytest.mark.integration
async def test_client_repository_crud_round_trip(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        c = await uow.clients.add(
            Client(
                full_name="Иван Иванов",
                phone="+7900xxx0001",
                source=ClientSource.telegram,
                telegram_id=98765,
            )
        )
        await uow.commit()
        client_id = c.id

    async with container.uow() as uow:
        loaded = await uow.clients.get(client_id)
        assert loaded is not None
        assert loaded.full_name == "Иван Иванов"
        assert loaded.source == ClientSource.telegram
        by_tg = await uow.clients.get_by_telegram_id(98765)
        assert by_tg is not None and by_tg.id == client_id

    await container.aclose()


@pytest.mark.integration
async def test_lead_repository_list_by_status(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crm.db.models.enums import ChannelKind

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        for i, status in enumerate([LeadStatus.new, LeadStatus.new, LeadStatus.qualified]):
            await uow.leads.add(
                Lead(
                    channel=ChannelKind.telegram,
                    raw_text=f"raw {i}",
                    status=status,
                )
            )
        await uow.commit()

    async with container.uow() as uow:
        new_leads = await uow.leads.list_by_status(LeadStatus.new)
        qualified_leads = await uow.leads.list_by_status(LeadStatus.qualified)

    assert len(new_leads) == 2
    assert len(qualified_leads) == 1

    await container.aclose()


@pytest.mark.integration
async def test_follow_up_check_constraint_rejects_zero_subjects(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from crm.db.models.enums import ChannelKind, FollowUpKind
    from crm.db.models.follow_up import FollowUp

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        bad = FollowUp(
            kind=FollowUpKind.reminder,
            scheduled_for=datetime.now(UTC) + timedelta(days=1),
            channel=ChannelKind.telegram,
            message_template="test",
        )
        uow.session.add(bad)
        with pytest.raises(IntegrityError):
            await uow.session.flush()
        await uow.rollback()

    await container.aclose()


@pytest.mark.integration
async def test_follow_up_check_constraint_rejects_two_subjects(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from crm.db.models.client import Client
    from crm.db.models.enums import (
        ChannelKind,
        ClientSource,
        FollowUpKind,
        LeadStatus,
    )
    from crm.db.models.follow_up import FollowUp
    from crm.db.models.lead import Lead

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        client = await uow.clients.add(Client(full_name="X", source=ClientSource.other))
        lead = await uow.leads.add(
            Lead(channel=ChannelKind.telegram, raw_text="r", status=LeadStatus.new)
        )
        await uow.commit()
        client_id, lead_id = client.id, lead.id

    async with container.uow() as uow:
        bad = FollowUp(
            lead_id=lead_id,
            client_id=client_id,
            kind=FollowUpKind.reminder,
            scheduled_for=datetime.now(UTC) + timedelta(days=1),
            channel=ChannelKind.telegram,
            message_template="test",
        )
        uow.session.add(bad)
        with pytest.raises(IntegrityError):
            await uow.session.flush()
        await uow.rollback()

    await container.aclose()


@pytest.mark.integration
async def test_follow_up_repository_list_due(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta

    from crm.db.models.enums import ChannelKind, FollowUpKind, FollowUpStatus, LeadStatus
    from crm.db.models.follow_up import FollowUp
    from crm.db.models.lead import Lead

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(channel=ChannelKind.telegram, raw_text="r", status=LeadStatus.new)
        )
        await uow.commit()
        lead_id = lead.id

    now = datetime.now(UTC)
    async with container.uow() as uow:
        await uow.follow_ups.add(
            FollowUp(
                lead_id=lead_id,
                kind=FollowUpKind.reminder,
                scheduled_for=now - timedelta(hours=1),
                channel=ChannelKind.telegram,
                message_template="due now",
                status=FollowUpStatus.pending,
            )
        )
        await uow.follow_ups.add(
            FollowUp(
                lead_id=lead_id,
                kind=FollowUpKind.reminder,
                scheduled_for=now + timedelta(days=1),
                channel=ChannelKind.telegram,
                message_template="future",
                status=FollowUpStatus.pending,
            )
        )
        await uow.commit()

    async with container.uow() as uow:
        due = await uow.follow_ups.list_due(now)

    assert len(due) == 1
    assert due[0].message_template == "due now"

    await container.aclose()


@pytest.mark.integration
async def test_document_polymorphic_owner_round_trip(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crm.db.models.document import Document
    from crm.db.models.enums import DocumentKind, DocumentOwnerType

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        await uow.documents.add(
            Document(
                owner_type=DocumentOwnerType.proposal,
                owner_id=42,
                kind=DocumentKind.gdoc,
                title="Proposal Doc",
                gdoc_id="abc123",
            )
        )
        await uow.documents.add(
            Document(
                owner_type=DocumentOwnerType.proposal,
                owner_id=43,
                kind=DocumentKind.gdoc,
                title="Other Proposal Doc",
                gdoc_id="def456",
            )
        )
        await uow.commit()

    async with container.uow() as uow:
        docs_42 = await uow.documents.list_for(DocumentOwnerType.proposal, 42)
        docs_43 = await uow.documents.list_for(DocumentOwnerType.proposal, 43)

    assert len(docs_42) == 1
    assert docs_42[0].title == "Proposal Doc"
    assert len(docs_43) == 1
    assert docs_43[0].gdoc_id == "def456"

    await container.aclose()


@pytest.mark.integration
async def test_event_append_only_log(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crm.db.models.event import Event

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    async with container.uow() as uow:
        await uow.events.add(
            Event(
                event_type="lead.created",
                aggregate_type="lead",
                aggregate_id=1,
                payload={"channel": "telegram"},
            )
        )
        await uow.events.add(
            Event(
                event_type="lead.qualified",
                aggregate_type="lead",
                aggregate_id=1,
                payload={"by": "operator"},
            )
        )
        await uow.commit()

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("lead", 1)

    assert [e.event_type for e in events] == ["lead.created", "lead.qualified"]

    await container.aclose()


@pytest.mark.integration
async def test_scheduled_job_list_pending_due_skips_future(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime, timedelta

    from crm.db.models.scheduled_job import ScheduledJob

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    now = datetime.now(UTC)

    async with container.uow() as uow:
        await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="due_now",
                payload={},
                run_at=now - timedelta(minutes=1),
            )
        )
        await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="future",
                payload={},
                run_at=now + timedelta(hours=1),
            )
        )
        await uow.commit()

    async with container.uow() as uow:
        due = await uow.scheduled_jobs.list_pending_due(now)

    assert len(due) == 1
    assert due[0].job_type == "due_now"

    await container.aclose()


@pytest.mark.integration
async def test_scheduled_job_idempotency_key_unique_partial(
    settings: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from sqlalchemy.exc import IntegrityError

    from crm.db.models.scheduled_job import ScheduledJob

    await _migrate(settings, monkeypatch)
    container = Container(settings)

    now = datetime.now(UTC)

    async with container.uow() as uow:
        await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="send_follow_up",
                payload={"follow_up_id": 1},
                run_at=now,
                idempotency_key="follow_up:1",
            )
        )
        await uow.commit()

    async with container.uow() as uow:
        await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="other",
                payload={},
                run_at=now,
                idempotency_key=None,
            )
        )
        await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type="other",
                payload={},
                run_at=now,
                idempotency_key=None,
            )
        )
        await uow.commit()

    async with container.uow() as uow:
        duplicate = ScheduledJob(
            job_type="send_follow_up",
            payload={"follow_up_id": 1},
            run_at=now,
            idempotency_key="follow_up:1",
        )
        uow.session.add(duplicate)
        with pytest.raises(IntegrityError):
            await uow.session.flush()
        await uow.rollback()

    await container.aclose()
