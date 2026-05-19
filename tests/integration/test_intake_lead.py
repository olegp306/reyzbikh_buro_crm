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
    from crm.adapters.ai.extractor import ExtractedLead

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

    from sqlalchemy import delete

    from crm.db.models.event import Event
    from crm.db.models.lead import Lead as LeadModel

    async with container.uow() as uow:
        await uow.session.execute(
            delete(Event).where(Event.aggregate_type == "lead", Event.aggregate_id == lead.id)
        )
        await uow.session.execute(delete(LeadModel).where(LeadModel.id == lead.id))
        await uow.commit()

    await container.aclose()
