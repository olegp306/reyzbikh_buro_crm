"""publish_proposal_to_gdoc — enqueue a worker job to publish a proposal.

Spec §5.1 steps 12-18. Fast use case: just enqueues a job with an
idempotency key so spamming the button doesn't create duplicates. The
worker handler (``handle_publish_proposal_to_gdoc``, T8) does the heavy
lifting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from crm.db.models.scheduled_job import ScheduledJob
from crm.scheduler.jobs import enqueue_job
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)

JOB_TYPE_PUBLISH_PROPOSAL = "publish_proposal_to_gdoc"


class ProposalNotFoundError(LookupError):
    """No proposal with the requested id."""


class ProposalNotReadyError(ValueError):
    """Proposal has no generated body — cannot publish."""


async def publish_proposal_to_gdoc(
    container: Container,
    *,
    proposal_id: int,
    operator_user_id: int | None,
) -> ScheduledJob:
    """Enqueue a job to publish ``proposal`` into Google Docs.

    Idempotent — repeated calls with the same proposal_id return the
    existing pending job (driven by ``idempotency_key``).

    Raises:
        ProposalNotFoundError: when the proposal does not exist.
        ProposalNotReadyError: when ``generated_text`` is empty.
    """
    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
        if not (proposal.generated_text or "").strip():
            raise ProposalNotReadyError(f"Proposal {proposal_id} has no body — generate it first")

        job = await enqueue_job(
            uow,
            job_type=JOB_TYPE_PUBLISH_PROPOSAL,
            payload={"proposal_id": proposal_id},
            idempotency_key=f"publish_proposal_to_gdoc:{proposal_id}",
            max_attempts=5,
        )

        await record_event(
            uow,
            event_type="proposal.publish_requested",
            aggregate_type="proposal",
            aggregate_id=proposal_id,
            payload={"job_id": job.id},
            actor_user_id=operator_user_id,
        )

        await uow.commit()
        result_job = job

    log.info(
        "publish_proposal_to_gdoc.enqueued",
        proposal_id=proposal_id,
        job_id=result_job.id,
    )
    return result_job


async def handle_publish_proposal_to_gdoc(container: Container, job: ScheduledJob) -> None:
    """Worker handler — stub. Real implementation lives in Task 8."""
    raise NotImplementedError("handle_publish_proposal_to_gdoc — implemented in Plan 5a Task 8")
