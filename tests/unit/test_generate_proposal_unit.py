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
