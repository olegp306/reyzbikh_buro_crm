"""Integration tests for record_follow_up_result."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    FollowUpKind,
    FollowUpStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.follow_up import FollowUp
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.use_cases.record_follow_up_result import (
    FollowUpNotFoundError,
    FollowUpNotSentError,
    FollowUpOutcome,
    record_follow_up_result,
)


async def _seed_sent_follow_up(container: Container) -> tuple[int, int, int]:
    """Returns (lead_id, proposal_id, follow_up_id) — proposal=sent, follow_up=sent."""
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                status=LeadStatus.proposal_sent,
            )
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.sent,
                generated_text="body",
                scope_summary="scope",
                currency="RUB",
                sent_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
        await uow.commit()
        follow_up = await uow.follow_ups.add(
            FollowUp(
                proposal_id=proposal.id,
                kind=FollowUpKind.status_check,
                scheduled_for=datetime.now(UTC),
                status=FollowUpStatus.sent,
                channel=ChannelKind.telegram,
                message_template="t",
                sent_at=datetime.now(UTC),
            )
        )
        await uow.commit()
        return lead.id, proposal.id, follow_up.id


@pytest.mark.integration
async def test_record_outcome_accepted_transitions_proposal_and_lead(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    lead_id, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    result = await record_follow_up_result(
        container,
        follow_up_id=follow_up_id,
        outcome=FollowUpOutcome.accepted,
        notes="client said yes",
        operator_user_id=None,
    )

    assert result.result_notes == "client said yes"

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        lead = await uow.leads.get(lead_id)
        assert proposal is not None
        assert proposal.status == ProposalStatus.accepted
        assert proposal.responded_at is not None
        assert lead is not None
        assert lead.status == LeadStatus.accepted

        events = await uow.events.list_for_aggregate("proposal", proposal_id)
    types = [e.event_type for e in events]
    assert "proposal.accepted" in types

    await container.aclose()


@pytest.mark.integration
async def test_record_outcome_declined_transitions_proposal_and_lead(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    lead_id, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    await record_follow_up_result(
        container,
        follow_up_id=follow_up_id,
        outcome=FollowUpOutcome.declined,
        notes="not interested",
        operator_user_id=None,
    )

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        lead = await uow.leads.get(lead_id)
        assert proposal is not None
        assert proposal.status == ProposalStatus.declined
        assert lead is not None
        assert lead.status == LeadStatus.declined

    await container.aclose()


@pytest.mark.integration
async def test_record_outcome_waiting_leaves_statuses_alone(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    lead_id, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    await record_follow_up_result(
        container,
        follow_up_id=follow_up_id,
        outcome=FollowUpOutcome.waiting,
        notes="still thinking",
        operator_user_id=None,
    )

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        lead = await uow.leads.get(lead_id)
        follow_up = await uow.follow_ups.get(follow_up_id)
        assert proposal is not None
        assert proposal.status == ProposalStatus.sent  # unchanged
        assert lead is not None
        assert lead.status == LeadStatus.proposal_sent  # unchanged
        assert follow_up is not None
        assert follow_up.result_notes == "still thinking"

        events = await uow.events.list_for_aggregate("follow_up", follow_up_id)
    types = [e.event_type for e in events]
    assert "follow_up.result_recorded" in types

    await container.aclose()


@pytest.mark.integration
async def test_record_follow_up_result_missing_raises(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    with pytest.raises(FollowUpNotFoundError):
        await record_follow_up_result(
            container,
            follow_up_id=999_999,
            outcome=FollowUpOutcome.waiting,
            notes="x",
            operator_user_id=None,
        )
    await container.aclose()


@pytest.mark.integration
async def test_record_outcome_accepted_twice_is_idempotent(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    """Re-clicking the same outcome must not duplicate proposal.accepted events."""
    container = Container(settings)
    _, proposal_id, follow_up_id = await _seed_sent_follow_up(container)

    await record_follow_up_result(
        container,
        follow_up_id=follow_up_id,
        outcome=FollowUpOutcome.accepted,
        notes="yes-1",
        operator_user_id=None,
    )

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        assert proposal is not None
        first_responded_at = proposal.responded_at

    await record_follow_up_result(
        container,
        follow_up_id=follow_up_id,
        outcome=FollowUpOutcome.accepted,
        notes="yes-2 (re-click)",
        operator_user_id=None,
    )

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        follow_up = await uow.follow_ups.get(follow_up_id)
        events = await uow.events.list_for_aggregate("proposal", proposal_id)

    assert proposal is not None
    assert proposal.status == ProposalStatus.accepted
    # responded_at not overwritten on the re-click.
    assert proposal.responded_at == first_responded_at
    # Notes still update (latest wins).
    assert follow_up is not None
    assert follow_up.result_notes == "yes-2 (re-click)"
    # Only ONE proposal.accepted event was emitted.
    accepted_events = [e for e in events if e.event_type == "proposal.accepted"]
    assert len(accepted_events) == 1

    await container.aclose()


@pytest.mark.integration
async def test_record_follow_up_result_rejects_pending(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(channel=ChannelKind.telegram, raw_text="r", status=LeadStatus.proposal_sent)
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.sent,
                generated_text="body",
                scope_summary="scope",
                currency="RUB",
            )
        )
        await uow.commit()
        follow_up = await uow.follow_ups.add(
            FollowUp(
                proposal_id=proposal.id,
                kind=FollowUpKind.status_check,
                scheduled_for=datetime.now(UTC),
                status=FollowUpStatus.pending,  # not yet sent
                channel=ChannelKind.telegram,
                message_template="t",
            )
        )
        await uow.commit()
        follow_up_id = follow_up.id

    with pytest.raises(FollowUpNotSentError):
        await record_follow_up_result(
            container,
            follow_up_id=follow_up_id,
            outcome=FollowUpOutcome.waiting,
            notes="x",
            operator_user_id=None,
        )

    await container.aclose()
