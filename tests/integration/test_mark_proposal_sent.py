"""Integration tests for mark_proposal_sent."""

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
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.use_cases.mark_proposal_sent import (
    ProposalNotFoundError,
    ProposalNotInDraftError,
    mark_proposal_sent,
)


async def _seed_draft_proposal(container: Container) -> tuple[int, int]:
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=ChannelKind.telegram,
                raw_text="r",
                status=LeadStatus.qualified,
            )
        )
        await uow.commit()
        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead.id,
                version=1,
                status=ProposalStatus.draft,
                generated_text="body",
                scope_summary="scope",
                currency="RUB",
            )
        )
        await uow.commit()
        return lead.id, proposal.id


@pytest.mark.integration
async def test_mark_proposal_sent_transitions_and_schedules_follow_up(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    lead_id, proposal_id = await _seed_draft_proposal(container)

    result = await mark_proposal_sent(container, proposal_id=proposal_id, operator_user_id=None)

    assert result.proposal.status == ProposalStatus.sent
    assert result.proposal.sent_at is not None
    assert result.follow_up.status == FollowUpStatus.pending
    assert result.follow_up.kind == FollowUpKind.status_check
    assert result.follow_up.channel == ChannelKind.telegram
    assert result.follow_up.proposal_id == proposal_id
    # Scheduled +3d
    delta = result.follow_up.scheduled_for - datetime.now(UTC)
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1)

    # Lead bumped
    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        assert lead is not None
        assert lead.status == LeadStatus.proposal_sent

        # Job enqueued
        from sqlalchemy import select

        from crm.db.models.scheduled_job import ScheduledJob

        jobs = list(
            (
                await uow.session.execute(
                    select(ScheduledJob).where(ScheduledJob.job_type == "send_follow_up")
                )
            )
            .scalars()
            .all()
        )
        assert len(jobs) == 1
        assert jobs[0].status == JobStatus.pending
        assert jobs[0].payload["follow_up_id"] == result.follow_up.id
        assert jobs[0].idempotency_key == f"send_follow_up:{result.follow_up.id}"

        events = await uow.events.list_for_aggregate("proposal", proposal_id)
    types = [e.event_type for e in events]
    assert "proposal.sent" in types
    assert "follow_up.scheduled" in types

    await container.aclose()


@pytest.mark.integration
async def test_mark_proposal_sent_rejects_non_draft(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    _, proposal_id = await _seed_draft_proposal(container)
    # Flip status to sent so the test exercises the guard.
    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        assert proposal is not None
        proposal.status = ProposalStatus.sent
        await uow.commit()

    with pytest.raises(ProposalNotInDraftError):
        await mark_proposal_sent(container, proposal_id=proposal_id, operator_user_id=None)

    await container.aclose()


@pytest.mark.integration
async def test_mark_proposal_sent_missing_proposal(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    with pytest.raises(ProposalNotFoundError):
        await mark_proposal_sent(container, proposal_id=999_999, operator_user_id=None)
    await container.aclose()
