"""record_follow_up_result use case.

Spec §5.1 steps 25-26. Operator (or worker via bot callback) records the
client's response to a follow-up. Optionally transitions the Proposal +
Lead statuses depending on the outcome:

  - accepted: Proposal=accepted, Lead=accepted; event proposal.accepted.
  - declined: Proposal=declined, Lead=declined; event proposal.declined.
  - waiting:  no status change.

In all cases ``FollowUp.result_notes`` is set and event
``follow_up.result_recorded`` is emitted.

Rejects if the follow-up is not in ``sent`` status (i.e. still pending
or already failed/cancelled).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import (
    FollowUpStatus,
    LeadStatus,
    ProposalStatus,
)
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.follow_up import FollowUp

log = structlog.get_logger(__name__)


class FollowUpOutcome(StrEnum):
    accepted = "accepted"
    declined = "declined"
    waiting = "waiting"


class FollowUpNotFoundError(LookupError):
    """No follow-up with the requested id."""


class FollowUpNotSentError(ValueError):
    """Follow-up is not in ``sent`` status — cannot record a result."""


async def record_follow_up_result(
    container: Container,
    *,
    follow_up_id: int,
    outcome: FollowUpOutcome,
    notes: str,
    operator_user_id: int | None,
) -> FollowUp:
    """Persist the operator's outcome notes + transition Proposal/Lead.

    Returns the updated ``FollowUp``.
    """
    now = datetime.now(UTC)

    async with container.uow() as uow:
        follow_up = await uow.follow_ups.get(follow_up_id)
        if follow_up is None:
            raise FollowUpNotFoundError(f"FollowUp {follow_up_id} not found")
        if follow_up.status != FollowUpStatus.sent:
            raise FollowUpNotSentError(
                f"FollowUp {follow_up_id} status={follow_up.status}, must be sent"
            )

        if follow_up.proposal_id is None:
            # v1 only handles proposal-subject follow-ups. Lead/client/project
            # follow-ups will arrive with future workflow cards.
            raise RuntimeError(
                f"FollowUp {follow_up_id} has no proposal_id — outcome flow only "
                "supports proposal-subject follow-ups in v1"
            )

        follow_up.result_notes = notes
        proposal = await uow.proposals.get(follow_up.proposal_id)
        if proposal is None:
            raise RuntimeError(
                f"FollowUp {follow_up_id} references missing Proposal {follow_up.proposal_id}"
            )
        lead = await uow.leads.get(proposal.lead_id)
        if lead is None:
            raise RuntimeError(f"Proposal {proposal.id} references missing Lead {proposal.lead_id}")

        already_final = (
            outcome == FollowUpOutcome.accepted and proposal.status == ProposalStatus.accepted
        ) or (outcome == FollowUpOutcome.declined and proposal.status == ProposalStatus.declined)
        if already_final:
            # Re-click of the same outcome — don't re-fire proposal.accepted/
            # declined or overwrite responded_at. Notes were already updated
            # above; we still emit a `follow_up.result_recorded` event so the
            # audit trail captures the re-click.
            log.info(
                "record_follow_up_result.idempotency_hit",
                follow_up_id=follow_up_id,
                outcome=outcome.value,
                proposal_status=proposal.status.value,
            )
            await record_event(
                uow,
                event_type="follow_up.result_recorded",
                aggregate_type="follow_up",
                aggregate_id=follow_up_id,
                payload={
                    "outcome": outcome.value,
                    "notes_preview": (notes or "")[:200],
                    "proposal_id": proposal.id,
                    "idempotency_hit": True,
                },
                actor_user_id=operator_user_id,
            )
            await uow.commit()
            return follow_up

        if outcome == FollowUpOutcome.accepted:
            proposal.status = ProposalStatus.accepted
            proposal.responded_at = now
            lead.status = LeadStatus.accepted
            await record_event(
                uow,
                event_type="proposal.accepted",
                aggregate_type="proposal",
                aggregate_id=proposal.id,
                payload={
                    "follow_up_id": follow_up_id,
                    "responded_at": now.isoformat(),
                },
                actor_user_id=operator_user_id,
            )
        elif outcome == FollowUpOutcome.declined:
            proposal.status = ProposalStatus.declined
            proposal.responded_at = now
            lead.status = LeadStatus.declined
            await record_event(
                uow,
                event_type="proposal.declined",
                aggregate_type="proposal",
                aggregate_id=proposal.id,
                payload={
                    "follow_up_id": follow_up_id,
                    "responded_at": now.isoformat(),
                },
                actor_user_id=operator_user_id,
            )

        await record_event(
            uow,
            event_type="follow_up.result_recorded",
            aggregate_type="follow_up",
            aggregate_id=follow_up_id,
            payload={
                "outcome": outcome.value,
                "notes_preview": (notes or "")[:200],
                "proposal_id": proposal.id,
            },
            actor_user_id=operator_user_id,
        )

        await uow.commit()
        result = follow_up

    log.info(
        "record_follow_up_result.done",
        follow_up_id=follow_up_id,
        outcome=outcome.value,
        proposal_id=proposal.id,
    )
    return result
