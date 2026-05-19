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
    """Worker handler: create a Google Doc for the proposal.

    Steps:
      1. Read proposal (and check whether a Document already exists for
         idempotency on retries).
      2. Outside any transaction, call ``gdocs.create_doc(...)``.
      3. INSERT Document; record ``proposal.published_to_gdoc`` event.
      4. Notify the first allowlisted operator with the resulting URL.

    Idempotency: if a Document with ``owner_type='proposal'`` and
    ``kind='gdoc'`` already exists for this proposal, skip the external
    call and treat the job as done. This handles the case where the
    previous worker crashed between gdocs.create_doc() and the
    Document INSERT (orphan Doc accepted, no duplicates created).
    """
    from crm.db.models.document import Document
    from crm.db.models.enums import DocumentKind, DocumentOwnerType

    proposal_id = int(job.payload["proposal_id"])

    async with container.uow() as uow:
        proposal = await uow.proposals.get(proposal_id)
        if proposal is None:
            raise RuntimeError(f"handle_publish_proposal_to_gdoc: Proposal {proposal_id} not found")

        existing = await uow.documents.list_for(DocumentOwnerType.proposal, proposal_id)
        already_gdoc = next((d for d in existing if d.kind == DocumentKind.gdoc), None)
        body = proposal.generated_text or ""
        scope = proposal.scope_summary or ""
        lead_id = proposal.lead_id

    if already_gdoc is not None:
        # First invocation already created the Document + notified the operator.
        # Lease-reclaim retries should be silent so the operator doesn't get
        # the same "опубликован" link twice.
        log.info(
            "handle_publish_proposal_to_gdoc.idempotency_hit",
            proposal_id=proposal_id,
            document_id=already_gdoc.id,
        )
        return

    if not body.strip():
        # Re-validate body at the worker side: the enqueue use case checks
        # too, but the proposal could have been wiped between enqueue and
        # worker tick. Refuse to create an empty GDoc.
        raise RuntimeError(
            f"Proposal {proposal_id} has empty generated_text — cannot publish to GDoc"
        )

    title = f"Proposal #{proposal_id} (lead #{lead_id}) — {scope[:60]}"
    ref = await container.gdocs.create_doc(title=title, body=body)

    async with container.uow() as uow:
        doc = await uow.documents.add(
            Document(
                owner_type=DocumentOwnerType.proposal,
                owner_id=proposal_id,
                kind=DocumentKind.gdoc,
                title=ref.title,
                url=ref.url,
                gdoc_id=ref.doc_id,
                mime_type="application/vnd.google-apps.document",
                uploaded_by_user_id=None,
            )
        )
        await record_event(
            uow,
            event_type="proposal.published_to_gdoc",
            aggregate_type="proposal",
            aggregate_id=proposal_id,
            payload={
                "document_id": doc.id,
                "gdoc_id": ref.doc_id,
                "url": ref.url,
            },
            actor_user_id=None,
        )
        await uow.commit()

    await _send_operator_link(container, proposal_id, ref.url)
    log.info(
        "handle_publish_proposal_to_gdoc.done",
        proposal_id=proposal_id,
        gdoc_id=ref.doc_id,
    )


async def _send_operator_link(container: Container, proposal_id: int, url: str) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    ids = container.settings.telegram_operator_ids
    if not ids:
        log.warning(
            "handle_publish_proposal_to_gdoc.no_operator_configured",
            proposal_id=proposal_id,
            url=url,
        )
        return
    chat_id = ids[0]
    # Inline keyboard with the mark-sent button so the operator can advance
    # the proposal to "sent" in one tap right from the notification.
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправлено клиенту",
                    callback_data=f"mark_sent:{proposal_id}",
                ),
            ],
        ],
    )
    try:
        await container.telegram_sender.send_message(
            chat_id=chat_id,
            text=f"📄 Proposal #{proposal_id} опубликован: {url}",
            reply_markup=kb,
        )
    except Exception as exc:
        log.warning(
            "handle_publish_proposal_to_gdoc.notify_failed",
            proposal_id=proposal_id,
            error=str(exc),
        )
