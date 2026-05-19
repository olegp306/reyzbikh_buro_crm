"""Proposal ORM model. Attached to a Lead; projects appear only after accept."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import ProposalStatus
from crm.db.models.mixins import TimestampMixin


class Proposal(TimestampMixin, Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, name="proposal_status", create_type=True),
        nullable=False,
        default=ProposalStatus.draft,
    )
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    scope_summary: Mapped[str] = mapped_column(Text, nullable=False)
    price_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="RUB")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Proposal id={self.id} lead_id={self.lead_id} status={self.status} v{self.version}>"
        )
