"""Document repository (polymorphic owner)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from crm.db.models.document import Document
from crm.db.models.enums import DocumentOwnerType
from crm.db.repositories.base import AsyncRepository


class DocumentRepository(AsyncRepository[Document]):
    model_cls = Document

    async def list_for(self, owner_type: DocumentOwnerType, owner_id: int) -> Sequence[Document]:
        result = await self._session.execute(
            select(Document)
            .where(
                Document.owner_type == owner_type,
                Document.owner_id == owner_id,
            )
            .order_by(Document.created_at.desc())
        )
        return result.scalars().all()
