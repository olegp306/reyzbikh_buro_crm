"""Integration tests for publish_proposal_to_gdoc use case (enqueue only)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.use_cases.publish_proposal_to_gdoc import (
    JOB_TYPE_PUBLISH_PROPOSAL,
    ProposalNotFoundError,
    ProposalNotReadyError,
    publish_proposal_to_gdoc,
)


async def _seed_proposal(
    container: Container,
    *,
    status: ProposalStatus,
    with_body: bool = True,
) -> int:
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
                status=status,
                generated_text="proposal body" if with_body else "",
                scope_summary="scope",
                currency="RUB",
            )
        )
        await uow.commit()
        return proposal.id


@pytest.mark.integration
async def test_publish_proposal_enqueues_job(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    proposal_id = await _seed_proposal(container, status=ProposalStatus.draft)

    job = await publish_proposal_to_gdoc(container, proposal_id=proposal_id, operator_user_id=None)

    assert job.job_type == JOB_TYPE_PUBLISH_PROPOSAL
    assert job.status == JobStatus.pending
    assert job.payload["proposal_id"] == proposal_id
    assert job.idempotency_key == f"publish_proposal_to_gdoc:{proposal_id}"

    async with container.uow() as uow:
        events = await uow.events.list_for_aggregate("proposal", proposal_id)
    types = [e.event_type for e in events]
    assert "proposal.publish_requested" in types

    await container.aclose()


@pytest.mark.integration
async def test_publish_proposal_is_idempotent(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    proposal_id = await _seed_proposal(container, status=ProposalStatus.draft)

    job1 = await publish_proposal_to_gdoc(container, proposal_id=proposal_id, operator_user_id=None)
    job2 = await publish_proposal_to_gdoc(container, proposal_id=proposal_id, operator_user_id=None)

    assert job1.id == job2.id

    await container.aclose()


@pytest.mark.integration
async def test_publish_proposal_rejects_empty_body(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    proposal_id = await _seed_proposal(container, status=ProposalStatus.draft, with_body=False)

    with pytest.raises(ProposalNotReadyError):
        await publish_proposal_to_gdoc(container, proposal_id=proposal_id, operator_user_id=None)

    await container.aclose()


@pytest.mark.integration
async def test_publish_proposal_missing_raises(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    with pytest.raises(ProposalNotFoundError):
        await publish_proposal_to_gdoc(container, proposal_id=999_999, operator_user_id=None)
    await container.aclose()
