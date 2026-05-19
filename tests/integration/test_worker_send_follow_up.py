"""End-to-end: enqueue + worker picks send_follow_up → operator notified."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

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
from crm.db.models.follow_up import FollowUp
from crm.db.models.lead import Lead
from crm.db.models.proposal import Proposal
from crm.db.models.scheduled_job import ScheduledJob
from crm.scheduler.handlers import JOB_HANDLERS, register_handler
from crm.scheduler.runner import _pick_due_jobs, _run_one
from crm.use_cases.send_follow_up import (
    JOB_TYPE_SEND_FOLLOW_UP,
    handle_send_follow_up,
)


@pytest.fixture(autouse=True)
def _wire_handler():
    JOB_HANDLERS.clear()
    register_handler(JOB_TYPE_SEND_FOLLOW_UP, handle_send_follow_up)
    yield
    JOB_HANDLERS.clear()


@pytest.mark.integration
async def test_worker_runs_send_follow_up_end_to_end(
    settings: Settings,
    engine: AsyncEngine,
    db_clean: None,
) -> None:
    container = Container(settings)
    sent: list[dict] = []

    async def _capture(*, chat_id: int, text: str, reply_markup=None, **_) -> None:
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    container.telegram_sender = MagicMock()
    container.telegram_sender.send_message = _capture  # type: ignore[assignment]

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
            )
        )
        await uow.commit()
        follow_up = await uow.follow_ups.add(
            FollowUp(
                proposal_id=proposal.id,
                kind=FollowUpKind.status_check,
                scheduled_for=datetime.now(UTC),
                status=FollowUpStatus.pending,
                channel=ChannelKind.telegram,
                message_template="reminder text",
            )
        )
        await uow.commit()
        job = await uow.scheduled_jobs.add(
            ScheduledJob(
                job_type=JOB_TYPE_SEND_FOLLOW_UP,
                payload={"follow_up_id": follow_up.id},
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                status=JobStatus.pending,
                max_attempts=5,
                idempotency_key=f"send_follow_up:{follow_up.id}",
            )
        )
        await uow.commit()
        follow_up_id = follow_up.id
        job_id = job.id

    picked = await _pick_due_jobs(container, worker_id="t1", limit=10)
    assert len(picked) == 1
    await _run_one(container, picked[0])

    async with container.uow() as uow:
        reloaded_follow_up = await uow.follow_ups.get(follow_up_id)
        reloaded_job = await uow.scheduled_jobs.get(job_id)
    assert reloaded_follow_up is not None
    assert reloaded_follow_up.status == FollowUpStatus.sent
    assert reloaded_job is not None
    assert reloaded_job.status == JobStatus.done
    assert len(sent) == 1

    await container.aclose()
