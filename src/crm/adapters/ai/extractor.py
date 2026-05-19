"""AI extractor: turns a raw lead message into structured fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExtractedLead:
    """Structured lead data produced by the AI extractor."""

    full_name: str | None = None
    contact: str | None = None
    project_type: str | None = None
    area_m2: float | None = None
    budget_range: str | None = None
    timeline: str | None = None
    summary: str = ""
    confidence: float = 0.0
    raw_response: dict = field(default_factory=dict)


class AIExtractor(Protocol):
    """Extracts structured fields from a raw lead message."""

    async def extract(self, raw_text: str) -> ExtractedLead: ...


class FakeAIExtractor:
    """Deterministic in-memory extractor for dev/test.

    Echoes the input back as a `summary` and tags everything as low confidence.
    """

    async def extract(self, raw_text: str) -> ExtractedLead:
        trimmed = raw_text.strip()
        summary = trimmed[:120] + ("..." if len(trimmed) > 120 else "")
        return ExtractedLead(
            full_name=None,
            contact=None,
            project_type=None,
            area_m2=None,
            budget_range=None,
            timeline=None,
            summary=summary or "(empty input)",
            confidence=0.0,
            raw_response={"provider": "fake", "input_chars": len(trimmed)},
        )
