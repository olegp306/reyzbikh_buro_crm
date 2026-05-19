"""Unit tests for record_follow_up_result — wiring without DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.db.models.enums import (
    FollowUpStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.use_cases.record_follow_up_result import (
    FollowUpNotFoundError,
    FollowUpNotSentError,
    FollowUpOutcome,
    record_follow_up_result,
)


def _stub_uow(follow_up, proposal, lead) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.follow_ups = MagicMock()
    uow.follow_ups.get = AsyncMock(return_value=follow_up)
    uow.proposals = MagicMock()
    uow.proposals.get = AsyncMock(return_value=proposal)
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=lead)
    return uow


def _stubs(outcome_status_change: bool = True):
    follow_up = MagicMock()
    follow_up.id = 1
    follow_up.status = FollowUpStatus.sent
    follow_up.proposal_id = 7
    proposal = MagicMock()
    proposal.id = 7
    proposal.lead_id = 9
    proposal.status = ProposalStatus.sent
    lead = MagicMock()
    lead.id = 9
    lead.status = LeadStatus.proposal_sent
    return follow_up, proposal, lead


@pytest.mark.asyncio
async def test_record_outcome_accepted_updates_all_three() -> None:
    follow_up, proposal, lead = _stubs()
    uow = _stub_uow(follow_up, proposal, lead)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    await record_follow_up_result(
        container,
        follow_up_id=1,
        outcome=FollowUpOutcome.accepted,
        notes="yes",
        operator_user_id=None,
    )

    assert proposal.status == ProposalStatus.accepted
    assert lead.status == LeadStatus.accepted
    assert follow_up.result_notes == "yes"


@pytest.mark.asyncio
async def test_record_outcome_declined_updates_all_three() -> None:
    follow_up, proposal, lead = _stubs()
    uow = _stub_uow(follow_up, proposal, lead)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    await record_follow_up_result(
        container,
        follow_up_id=1,
        outcome=FollowUpOutcome.declined,
        notes="no",
        operator_user_id=None,
    )

    assert proposal.status == ProposalStatus.declined
    assert lead.status == LeadStatus.declined


@pytest.mark.asyncio
async def test_record_outcome_waiting_leaves_statuses() -> None:
    follow_up, proposal, lead = _stubs()
    uow = _stub_uow(follow_up, proposal, lead)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    await record_follow_up_result(
        container,
        follow_up_id=1,
        outcome=FollowUpOutcome.waiting,
        notes="thinking",
        operator_user_id=None,
    )

    assert proposal.status == ProposalStatus.sent
    assert lead.status == LeadStatus.proposal_sent
    assert follow_up.result_notes == "thinking"


@pytest.mark.asyncio
async def test_record_missing_raises() -> None:
    uow = _stub_uow(None, None, None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(FollowUpNotFoundError):
        await record_follow_up_result(
            container,
            follow_up_id=1,
            outcome=FollowUpOutcome.waiting,
            notes="x",
            operator_user_id=None,
        )


@pytest.mark.asyncio
async def test_record_rejects_non_sent() -> None:
    follow_up, proposal, lead = _stubs()
    follow_up.status = FollowUpStatus.pending
    uow = _stub_uow(follow_up, proposal, lead)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(FollowUpNotSentError):
        await record_follow_up_result(
            container,
            follow_up_id=1,
            outcome=FollowUpOutcome.waiting,
            notes="x",
            operator_user_id=None,
        )
