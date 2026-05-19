"""Integration tests for qualify_lead."""

from __future__ import annotations

import pytest
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


@pytest.mark.integration
async def test_qualify_lead_promotes_to_qualified(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
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
    db_clean: None,
) -> None:
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
    db_clean: None,
) -> None:
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
    db_clean: None,
) -> None:
    container = Container(settings)

    with pytest.raises(LeadNotFoundError):
        await qualify_lead(container, lead_id=999_999, operator_user_id=None)

    await container.aclose()


@pytest.mark.integration
async def test_qualify_lead_rejects_terminal_states(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)

    lead_id = await _add_lead(container, status=LeadStatus.archived)

    with pytest.raises(LeadCannotQualifyError):
        await qualify_lead(container, lead_id=lead_id, operator_user_id=None)

    await container.aclose()
