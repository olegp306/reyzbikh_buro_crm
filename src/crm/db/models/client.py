"""Client ORM model. A Client is a *party*, not an inbound event."""

from __future__ import annotations

from sqlalchemy import BigInteger, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import ClientSource
from crm.db.models.mixins import TimestampMixin


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[ClientSource | None] = mapped_column(
        Enum(ClientSource, name="client_source", create_type=True),
        nullable=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"<Client id={self.id} full_name={self.full_name!r}>"
