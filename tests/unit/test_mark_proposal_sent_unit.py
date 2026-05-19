"""Unit tests for mark_proposal_sent — wiring & error paths without DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.db.models.enums import LeadStatus, ProposalStatus
from crm.use_cases.mark_proposal_sent import (
    ProposalNotFoundError,
    ProposalNotInDraftError,
    mark_proposal_sent,
)


def _stub_uow(proposal, lead, follow_up_returned, job_returned) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.proposals = MagicMock()
    uow.proposals.get = AsyncMock(return_value=proposal)
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=lead)
    uow.follow_ups = MagicMock()
    uow.follow_ups.add = AsyncMock(return_value=follow_up_returned)
    uow.scheduled_jobs = MagicMock()
    uow.scheduled_jobs.get_by_idempotency_key = AsyncMock(return_value=None)
    uow.scheduled_jobs.add = AsyncMock(return_value=job_returned)
    return uow


@pytest.mark.asyncio
async def test_mark_proposal_sent_happy_path() -> None:
    proposal = MagicMock()
    proposal.id = 1
    proposal.lead_id = 7
    proposal.status = ProposalStatus.draft
    lead = MagicMock()
    lead.id = 7
    lead.status = LeadStatus.qualified
    follow_up = MagicMock()
    follow_up.id = 42
    job = MagicMock()
    job.id = 99

    uow = _stub_uow(proposal, lead, follow_up, job)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    result = await mark_proposal_sent(container, proposal_id=1, operator_user_id=None)

    assert proposal.status == ProposalStatus.sent
    assert lead.status == LeadStatus.proposal_sent
    assert result.proposal is proposal
    assert result.follow_up is follow_up
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_proposal_sent_missing_proposal() -> None:
    uow = _stub_uow(None, None, None, None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(ProposalNotFoundError):
        await mark_proposal_sent(container, proposal_id=1, operator_user_id=None)


@pytest.mark.asyncio
async def test_mark_proposal_sent_non_draft_rejected() -> None:
    proposal = MagicMock()
    proposal.id = 1
    proposal.status = ProposalStatus.sent
    uow = _stub_uow(proposal, None, None, None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(ProposalNotInDraftError):
        await mark_proposal_sent(container, proposal_id=1, operator_user_id=None)
