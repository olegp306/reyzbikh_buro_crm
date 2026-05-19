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

    proposal = await generate_proposal(container, lead_id=lead_id, operator_user_id=None)

    assert proposal.status == ProposalStatus.draft
    assert proposal.lead_id == lead_id
    assert proposal.version == 1
    assert proposal.generated_text  # FakeProposalWriter returns non-empty body
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

    proposal = await generate_proposal(container, lead_id=lead_id, operator_user_id=None)

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
