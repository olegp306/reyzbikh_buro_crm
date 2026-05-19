"""End-to-end: enqueue publish_proposal_to_gdoc → worker picks → Document + Telegram."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crm.config import Settings
from crm.container import Container
from crm.db.models.enums import (
    ChannelKind,
    DocumentKind,
    DocumentOwnerType,
    JobStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.scheduler.handlers import JOB_HANDLERS, register_handler
from crm.scheduler.runner import _pick_due_jobs, _run_one
from crm.use_cases.publish_proposal_to_gdoc import (
    JOB_TYPE_PUBLISH_PROPOSAL,
    handle_publish_proposal_to_gdoc,
    publish_proposal_to_gdoc,
)


@pytest.fixture(autouse=True)
def _wire_handler():
    JOB_HANDLERS.clear()
    register_handler(JOB_TYPE_PUBLISH_PROPOSAL, handle_publish_proposal_to_gdoc)
    yield
    JOB_HANDLERS.clear()


async def _seed_proposal(container: Container) -> int:
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
                generated_text="body of the proposal",
                scope_summary="kitchen",
                currency="RUB",
            )
        )
        await uow.commit()
        return proposal.id


@pytest.mark.integration
async def test_worker_publishes_proposal_to_gdoc_end_to_end(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

    proposal_id = await _seed_proposal(container)
    await publish_proposal_to_gdoc(container, proposal_id=proposal_id, operator_user_id=None)

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        docs = await uow.documents.list_for(DocumentOwnerType.proposal, proposal_id)
        events = await uow.events.list_for_aggregate("proposal", proposal_id)
        reloaded_job = await uow.scheduled_jobs.get(picked[0].id)

    assert len(docs) == 1
    assert docs[0].kind == DocumentKind.gdoc
    assert docs[0].url.startswith("https://docs.example.com/")
    assert docs[0].gdoc_id.startswith("fake-")

    types = [e.event_type for e in events]
    assert "proposal.publish_requested" in types
    assert "proposal.published_to_gdoc" in types

    assert reloaded_job is not None
    assert reloaded_job.status == JobStatus.done

    assert len(sent) == 1
    assert "опубликован" in sent[0]["text"]
    assert "https://docs.example.com/" in sent[0]["text"]

    await container.aclose()


@pytest.mark.integration
async def test_worker_gdocs_handler_is_idempotent_on_retry(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    """Simulate: handler ran once, then ran AGAIN after a retry — no duplicate Doc."""
    container = Container(settings)

    proposal_id = await _seed_proposal(container)
    await publish_proposal_to_gdoc(container, proposal_id=proposal_id, operator_user_id=None)

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    job = picked[0]
    # Run handler twice (simulating retry / replay).
    await handle_publish_proposal_to_gdoc(container, job)
    await handle_publish_proposal_to_gdoc(container, job)

    async with container.uow() as uow:
        docs = await uow.documents.list_for(DocumentOwnerType.proposal, proposal_id)
    assert len(docs) == 1  # single document despite two handler invocations

    # FakeGDocsClient.created records ONE create — verify we didn't hit it twice.
    assert len(container.gdocs.created) == 1

    await container.aclose()
