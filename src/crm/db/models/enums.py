"""Python `StrEnum`s mirrored as PostgreSQL native ENUM types.

Naming: each PG enum gets an explicit `name=` in the model column so we can
ALTER TYPE it safely in future migrations.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    owner = "owner"
    architect = "architect"
    assistant = "assistant"


class ClientSource(StrEnum):
    telegram = "telegram"
    referral = "referral"
    website = "website"
    walk_in = "walk_in"
    other = "other"


class ChannelKind(StrEnum):
    """Inbound channel for a Lead or outbound channel for a FollowUp."""

    telegram = "telegram"
    email = "email"
    web_form = "web_form"
    manual = "manual"


class LeadStatus(StrEnum):
    new = "new"
    qualifying = "qualifying"
    qualified = "qualified"
    proposal_sent = "proposal_sent"
    accepted = "accepted"
    declined = "declined"
    archived = "archived"


class ProjectStatus(StrEnum):
    proposed = "proposed"
    contract_signed = "contract_signed"
    in_progress = "in_progress"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class ProposalStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    declined = "declined"
    revised = "revised"


class FollowUpKind(StrEnum):
    reminder = "reminder"
    status_check = "status_check"
    deadline = "deadline"


class FollowUpStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    cancelled = "cancelled"
    failed = "failed"


class DocumentOwnerType(StrEnum):
    lead = "lead"
    client = "client"
    project = "project"
    proposal = "proposal"
    contract = "contract"


class DocumentKind(StrEnum):
    gdoc = "gdoc"
    pdf = "pdf"
    image = "image"
    link = "link"
    other = "other"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class ContractStatusComputed(StrEnum):
    """Not a stored column — exposed via a Python property.

    Defined here so the rest of the system can refer to it symbolically.
    """

    draft = "draft"
    signed = "signed"
