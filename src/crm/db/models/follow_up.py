"""FollowUp ORM model.

Polymorphic subject: exactly one of `lead_id`, `proposal_id`, `client_id`,
`project_id` must be non-null. Enforced via a CHECK constraint at the table
level so the DB rejects malformed inserts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import ChannelKind, FollowUpKind, FollowUpStatus
from crm.db.models.mixins import TimestampMixin


class FollowUp(TimestampMixin, Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True
    )
    proposal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=True
    )
    client_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[FollowUpKind] = mapped_column(
        Enum(FollowUpKind, name="follow_up_kind", create_type=True),
        nullable=False,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus, name="follow_up_status", create_type=True),
        nullable=False,
        default=FollowUpStatus.pending,
    )
    channel: Mapped[ChannelKind] = mapped_column(
        Enum(ChannelKind, name="channel_kind", create_type=False),
        nullable=False,
    )
    message_template: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(lead_id, proposal_id, client_id, project_id) = 1",
            name="ck_follow_ups_exactly_one_subject",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FollowUp id={self.id} kind={self.kind} status={self.status} "
            f"scheduled_for={self.scheduled_for.isoformat() if self.scheduled_for else None}>"
        )
