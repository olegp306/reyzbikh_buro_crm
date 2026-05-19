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
                raw_text="r",
                status=status,
                extracted_data=extracted_data or {},
            )
        )
        await uow.commit()
        return lead.id


async def _teardown_lead(
    container: Container,
    lead_id: int,
    *,
    client_id: int | None = None,
) -> None:
    """Remove test rows so later integration tests see a clean DB."""
    async with container.uow() as uow:
        for event in await uow.events.list_for_aggregate("lead", lead_id):
            await uow.events.delete(event)
        lead = await uow.leads.get(lead_id)
        if lead is not None:
            await uow.leads.delete(lead)
        if client_id is not None:
            client = await uow.clients.get(client_id)
            if client is not None:
                await uow.clients.delete(client)
        await uow.commit()


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

    await _teardown_lead(container, lead_id, client_id=lead.client_id)
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

    await _teardown_lead(container, lead_id)
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

    lead = await qualify_lead(container, lead_id=lead_id, operator_user_id=None)

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("lead", lead_id)
    types = [e.event_type for e in events]
    assert "lead.qualified" in types

    await _teardown_lead(container, lead_id, client_id=lead.client_id)
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

    await _teardown_lead(container, lead_id)
    await container.aclose()
