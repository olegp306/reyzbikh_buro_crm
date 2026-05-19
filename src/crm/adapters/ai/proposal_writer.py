"""AI proposal writer: generates a draft proposal body for a lead."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProposalDraft:
    """A draft proposal produced by the AI writer."""

    body: str
    scope_summary: str
    price_estimate: float | None = None
    currency: str = "RUB"


class ProposalWriter(Protocol):
    """Generates a draft proposal for a given lead."""

    async def generate(
        self,
        *,
        lead_summary: str,
        extracted: dict,
    ) -> ProposalDraft: ...


class FakeProposalWriter:
    """Deterministic in-memory proposal writer for dev/test."""

    async def generate(
        self,
        *,
        lead_summary: str,
        extracted: dict,
    ) -> ProposalDraft:
        body = (
            "Здравствуйте!\n\n"
            "Спасибо за обращение. Ниже — предварительный план работы.\n\n"
            f"Краткое описание задачи: {lead_summary}\n\n"
            "Этапы: 1) встреча и обмер, 2) эскиз, 3) рабочая документация.\n\n"
            "С уважением, архитектурное бюро."  # noqa: RUF001
        )
        return ProposalDraft(
            body=body,
            scope_summary=lead_summary[:200],
            price_estimate=None,
            currency="RUB",
        )
