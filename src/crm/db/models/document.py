"""Document ORM model. Polymorphic via (owner_type, owner_id) — no FK."""

from __future__ import annotations

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from crm.db.base import Base
from crm.db.models.enums import DocumentKind, DocumentOwnerType
from crm.db.models.mixins import CreatedAtMixin


class Document(CreatedAtMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_type: Mapped[DocumentOwnerType] = mapped_column(
        Enum(DocumentOwnerType, name="document_owner_type", create_type=True),
        nullable=False,
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind", create_type=True),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    gdoc_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_documents_owner", "owner_type", "owner_id"),)

    def __repr__(self) -> str:
        return f"<Document id={self.id} owner={self.owner_type}:{self.owner_id} kind={self.kind}>"
