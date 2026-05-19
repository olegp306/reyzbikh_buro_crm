"""intake_lead use case — first step of the lead workflow.

Spec §5.1, steps 1-5. Two transactions:

  TX1: INSERT Lead (status=new) + record event lead.created → commit.
  --- AI extractor call happens OUTSIDE any DB transaction ---
  TX2: UPDATE Lead with extracted data + status=qualifying + event
       lead.extracted → commit. If the AI call failed, instead record
       lead.extraction_failed and leave status=new.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import ChannelKind, LeadStatus
from crm.db.models.lead import Lead
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)


async def intake_lead(
    container: Container,
    *,
    raw_text: str,
    channel: ChannelKind,
    channel_message_id: str | None,
    operator_user_id: int | None,
) -> Lead:
    """Ingest a raw lead message and run AI extraction.

    Returns the Lead with its final post-extraction state. The Lead is
    always persisted even if extraction fails — operators can re-run
    extraction manually later.
    """
    async with container.uow() as uow:
        lead = await uow.leads.add(
            Lead(
                channel=channel,
                channel_message_id=channel_message_id,
                raw_text=raw_text,
                status=LeadStatus.new,
                assigned_to_user_id=operator_user_id,
            )
        )
        await record_event(
            uow,
            event_type="lead.created",
            aggregate_type="lead",
            aggregate_id=lead.id,
            payload={
                "channel": channel.value,
                "channel_message_id": channel_message_id,
                "raw_text_chars": len(raw_text),
            },
            actor_user_id=operator_user_id,
        )
        await uow.commit()
        lead_id = lead.id

    log.info("intake_lead.created", lead_id=lead_id)

    try:
        extracted = await container.ai_extractor.extract(raw_text)
        extraction_error: Exception | None = None
    except Exception as exc:
        log.warning(
            "intake_lead.extraction_failed",
            lead_id=lead_id,
            error=str(exc),
        )
        extracted = None
        extraction_error = exc

    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        assert lead is not None  # we just inserted it

        if extracted is not None:
            lead.summary = extracted.summary
            lead.extracted_data = dict(extracted.raw_response)
            lead.status = LeadStatus.qualifying
            await record_event(
                uow,
                event_type="lead.extracted",
                aggregate_type="lead",
                aggregate_id=lead_id,
                payload={
                    "summary": extracted.summary,
                    "confidence": extracted.confidence,
                },
                actor_user_id=operator_user_id,
            )
        else:
            assert extraction_error is not None
            lead.extracted_data = {
                "_extraction_failed": True,
                "error": str(extraction_error),
            }
            await record_event(
                uow,
                event_type="lead.extraction_failed",
                aggregate_type="lead",
                aggregate_id=lead_id,
                payload={"error": str(extraction_error)},
                actor_user_id=operator_user_id,
            )

        await uow.commit()
        result = lead

    log.info(
        "intake_lead.finished",
        lead_id=lead_id,
        status=result.status,
        ai_ok=extraction_error is None,
    )
    return result
