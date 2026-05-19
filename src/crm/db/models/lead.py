"""Lead ORM model. Inbound event; may or may not be promoted to a Client."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import ChannelKind, LeadStatus
from crm.db.models.mixins import TimestampMixin


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[ChannelKind] = mapped_column(
        Enum(ChannelKind, name="channel_kind", create_type=True),
        nullable=False,
    )
    channel_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status", create_type=True),
        nullable=False,
        default=LeadStatus.new,
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Lead id={self.id} status={self.status} channel={self.channel}>"
