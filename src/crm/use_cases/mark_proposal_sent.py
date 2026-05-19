"""mark_proposal_sent use case.

Spec §5.1 step 20-21. Single-transaction transition:

  - Proposal.status = sent, sent_at = now
  - Lead.status     = proposal_sent
  - INSERT FollowUp(proposal_id, kind=status_check, scheduled_for=now+3d,
                    channel=telegram, status=pending, message_template=<text>)
  - ENQUEUE job send_follow_up(payload={follow_up_id}, run_at=scheduled_for,
                               idempotency_key=f"send_follow_up:{id}")
  - Events: proposal.sent, follow_up.scheduled

Idempotency is enforced by status-guard: only Proposals in `draft` may be
marked sent. Operators who double-click will see ``ProposalNotInDraftError``
on the second click.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import (
    ChannelKind,
    FollowUpKind,
    FollowUpStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.db.models.follow_up import FollowUp
from crm.scheduler.jobs import enqueue_job
from crm.use_cases.events import record_event
from crm.use_cases.send_follow_up import JOB_TYPE_SEND_FOLLOW_UP

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.proposal import Proposal

log = structlog.get_logger(__name__)

# Default reminder lag — matches spec §5.5 ("FollowUp +3d").
FOLLOW_UP_DELAY = timedelta(days=3)


class ProposalNotFoundError(LookupError):
    """No proposal with the requested id."""


class ProposalNotInDraftError(ValueError):
    """Proposal is not in status=draft — cannot transition to sent."""


@dataclass
class MarkSentResult:
    """Returned to the caller so the bot handler can render context."""

    proposal: Proposal
    follow_up: FollowUp


async def mark_proposal_sent(
    container: Container,
    *,
    proposal_id: int,
    operator_user_id: int | None,
) -> MarkSentResult:
    """Transition Proposal → sent + Lead → proposal_sent and schedule a +3d follow-up."""
    now = datetime.now(UTC)
    scheduled_for = now + FOLLOW_UP_DELAY

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
        if proposal.status != ProposalStatus.draft:
            raise ProposalNotInDraftError(
                f"Proposal {proposal_id} status={proposal.status}, must be draft"
            )

        lead = await uow.leads.get(proposal.lead_id)
        if lead is None:
            raise RuntimeError(
                f"mark_proposal_sent: Lead {proposal.lead_id} for Proposal "
                f"{proposal_id} not found (orphan proposal)"
            )

        proposal.status = ProposalStatus.sent
        proposal.sent_at = now
        lead.status = LeadStatus.proposal_sent

        reminder_text = (
            f"⏰ 3 дня назад отправили Proposal #{proposal_id} "
            f"(lead #{lead.id}). Клиент откликнулся?"
        )

        follow_up = await uow.follow_ups.add(
            FollowUp(
                proposal_id=proposal_id,
                kind=FollowUpKind.status_check,
                scheduled_for=scheduled_for,
                status=FollowUpStatus.pending,
                channel=ChannelKind.telegram,
                message_template=reminder_text,
            )
        )

        job = await enqueue_job(
            uow,
            job_type=JOB_TYPE_SEND_FOLLOW_UP,
            payload={"follow_up_id": follow_up.id},
            run_at=scheduled_for,
            idempotency_key=f"send_follow_up:{follow_up.id}",
            max_attempts=5,
        )

        await record_event(
            uow,
            event_type="proposal.sent",
            aggregate_type="proposal",
            aggregate_id=proposal_id,
            payload={"sent_at": now.isoformat(), "lead_id": lead.id},
            actor_user_id=operator_user_id,
        )
        await record_event(
            uow,
            event_type="follow_up.scheduled",
            aggregate_type="proposal",
            aggregate_id=proposal_id,
            payload={
                "follow_up_id": follow_up.id,
                "scheduled_for": scheduled_for.isoformat(),
                "job_id": job.id,
            },
            actor_user_id=operator_user_id,
        )

        await uow.commit()
        result = MarkSentResult(proposal=proposal, follow_up=follow_up)

    log.info(
        "mark_proposal_sent.done",
        proposal_id=proposal_id,
        follow_up_id=result.follow_up.id,
        scheduled_for=scheduled_for.isoformat(),
        job_id=job.id,
    )
    return result
