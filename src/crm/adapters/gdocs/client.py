"""Google Docs client adapter."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GDocRef:
    """Reference to a Google Doc that was created or written."""

    doc_id: str
    url: str
    title: str


class GDocsClient(Protocol):
    """Creates Google Docs and writes content into them."""

    async def create_doc(self, *, title: str, body: str) -> GDocRef: ...


class FakeGDocsClient:
    """In-memory GDocs that just generates a fake URL.

    Stores every created "document" in `self.created` for assertions.
    """

    def __init__(self) -> None:
        self.created: list[GDocRef] = []

    async def create_doc(self, *, title: str, body: str) -> GDocRef:
        doc_id = f"fake-{uuid.uuid4()}"
        ref = GDocRef(
            doc_id=doc_id,
            url=f"https://docs.example.com/{doc_id}",
            title=title,
        )
        self.created.append(ref)
        return ref
