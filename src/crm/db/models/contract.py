"""Contract ORM model.

`signed_at IS NULL` means draft; otherwise signed. We expose a computed
`status` property for code readability — not a stored column.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import ContractStatusComputed
from crm.db.models.mixins import TimestampMixin


class Contract(TimestampMixin, Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    proposal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    contract_number: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="RUB")

    @property
    def status(self) -> ContractStatusComputed:
        return (
            ContractStatusComputed.signed
            if self.signed_at is not None
            else ContractStatusComputed.draft
        )

    def __repr__(self) -> str:
        return f"<Contract id={self.id} project_id={self.project_id} status={self.status}>"
