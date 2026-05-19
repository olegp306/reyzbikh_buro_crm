"""generate_proposal use case.

Spec §5.1 steps 8-11. Two transactions:

  TX1: validate lead is qualified, INSERT Proposal(status=draft, version=1)
       and record event proposal.created.
  --- AI proposal_writer.generate(...) runs OUTSIDE any DB transaction ---
  TX2 (success): UPDATE Proposal with body/scope/price/currency, record
       event proposal.generated.
  TX2 (failure): leave generated_text="", record event
       proposal.generation_failed with the error string. Operator can
       re-trigger generation later.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import LeadStatus, ProposalStatus
from crm.db.models.proposal import Proposal
from crm.use_cases.events import record_event
from crm.use_cases.qualify_lead import LeadNotFoundError

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)


class LeadNotQualifiedError(ValueError):
    """Lead is not in status qualified — cannot generate a proposal."""


async def generate_proposal(
    container: Container,
    *,
    lead_id: int,
    operator_user_id: int | None,
) -> Proposal:
    """Create a draft Proposal and fill it via AI proposal writer."""
    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(f"Lead {lead_id} not found")
        if lead.status != LeadStatus.qualified:
            raise LeadNotQualifiedError(f"Lead {lead_id} status={lead.status}, must be qualified")

        proposal = await uow.proposals.add(
            Proposal(
                lead_id=lead_id,
                version=1,
                status=ProposalStatus.draft,
                generated_text="",
                scope_summary="",
                currency="RUB",
            )
        )
        await record_event(
            uow,
            event_type="proposal.created",
            aggregate_type="proposal",
            aggregate_id=proposal.id,
            payload={"lead_id": lead_id, "version": 1},
            actor_user_id=operator_user_id,
        )
        lead_summary = lead.summary or ""
        extracted_snapshot = dict(lead.extracted_data or {})
        await uow.commit()
        proposal_id = proposal.id

    log.info("generate_proposal.created", proposal_id=proposal_id, lead_id=lead_id)

    try:
        draft = await container.proposal_writer.generate(
            lead_summary=lead_summary,
            extracted=extracted_snapshot,
        )
        generation_error: Exception | None = None
    except Exception as exc:
        log.warning(
            "generate_proposal.failed",
            proposal_id=proposal_id,
            error=str(exc),
        )
        draft = None
        generation_error = exc

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise RuntimeError(
                f"generate_proposal: Proposal {proposal_id} disappeared between TX1 and TX2"
            )

        if draft is not None:
            proposal.generated_text = draft.body
            proposal.scope_summary = draft.scope_summary
            proposal.price_estimate = (
                Decimal(str(draft.price_estimate)) if draft.price_estimate is not None else None
            )
            proposal.currency = draft.currency or "RUB"
            await record_event(
                uow,
                event_type="proposal.generated",
                aggregate_type="proposal",
                aggregate_id=proposal_id,
                payload={
                    "scope_summary": draft.scope_summary,
                    "price_estimate": (
                        float(draft.price_estimate) if draft.price_estimate is not None else None
                    ),
                    "currency": proposal.currency,
                    "body_chars": len(draft.body),
                },
                actor_user_id=operator_user_id,
            )
        else:
            if generation_error is None:
                raise RuntimeError(
                    "generate_proposal: invariant broken — draft is None but no error"
                )
            await record_event(
                uow,
                event_type="proposal.generation_failed",
                aggregate_type="proposal",
                aggregate_id=proposal_id,
                payload={"error": str(generation_error)},
                actor_user_id=operator_user_id,
            )

        await uow.commit()
        result = proposal

    log.info(
        "generate_proposal.finished",
        proposal_id=proposal_id,
        ai_ok=generation_error is None,
    )
    return result
