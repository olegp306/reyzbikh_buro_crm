"""qualify_lead use case.

Spec §5.1 step 7. Promotes a Lead from `qualifying`/`new` to `qualified`
and — if the extracted data has enough info — creates a Client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from crm.db.models.client import Client
from crm.db.models.enums import ClientSource, LeadStatus
from crm.db.models.lead import Lead
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container

log = structlog.get_logger(__name__)


class LeadNotFoundError(LookupError):
    """The requested lead does not exist."""


class LeadCannotQualifyError(ValueError):
    """The lead is in a status from which it cannot be qualified."""


_QUALIFIABLE_FROM: frozenset[LeadStatus] = frozenset({LeadStatus.new, LeadStatus.qualifying})


async def qualify_lead(
    container: Container,
    *,
    lead_id: int,
    operator_user_id: int | None,
) -> Lead:
    """Move a Lead to `qualified` and optionally materialise a Client.

    Raises:
        LeadNotFoundError: no Lead with this id.
        LeadCannotQualifyError: Lead is in a status that doesn't allow
            qualification (e.g. already `accepted`, `declined`, or
            `archived`).
    """
    async with container.uow() as uow:
        lead = await uow.leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(f"Lead {lead_id} not found")
        if lead.status not in _QUALIFIABLE_FROM:
            raise LeadCannotQualifyError(
                f"Lead {lead_id} is in status {lead.status}, cannot qualify"
            )

        created_client_id: int | None = None
        if lead.client_id is None:
            client = _maybe_build_client(lead)
            if client is not None:
                client = await uow.clients.add(client)
                lead.client_id = client.id
                created_client_id = client.id

        lead.status = LeadStatus.qualified

        await record_event(
            uow,
            event_type="lead.qualified",
            aggregate_type="lead",
            aggregate_id=lead.id,
            payload={"created_client_id": created_client_id},
            actor_user_id=operator_user_id,
        )

        await uow.commit()
        result = lead

    log.info(
        "qualify_lead.done",
        lead_id=lead_id,
        created_client_id=created_client_id,
    )
    return result


def _maybe_build_client(lead: Lead) -> Client | None:
    """Return a fresh Client built from extracted_data, or None.

    Heuristic: we need at least a non-empty ``full_name``. ``phone``,
    ``email``, and ``telegram_id`` are optional but populated when
    present in extracted_data.
    """
    data = lead.extracted_data or {}
    if data.get("_extraction_failed"):
        return None
    full_name = data.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        return None

    contact = data.get("contact")
    phone: str | None = None
    email: str | None = None
    if isinstance(contact, str):
        if "@" in contact:
            email = contact
        else:
            phone = contact

    return Client(
        full_name=full_name.strip(),
        phone=phone,
        email=email,
        source=ClientSource.telegram,
        notes="",
    )
