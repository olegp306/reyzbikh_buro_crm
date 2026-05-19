"""OpenAI implementation of the AIExtractor protocol.

Uses chat completions with ``response_format={"type": "json_object"}`` and
a Jinja-rendered system prompt. The model is instructed (via the prompt)
to return strictly the documented JSON shape; we parse + coerce here.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import structlog

from crm.adapters.ai.extractor import ExtractedLead
from crm.prompts import render

log = structlog.get_logger(__name__)


class _OpenAIClientLike(Protocol):
    """Subset of openai.AsyncOpenAI we depend on — kept narrow for testing."""

    chat: Any


class OpenAIExtractor:
    """Calls OpenAI to extract structured fields from a raw lead message."""

    def __init__(self, *, client: _OpenAIClientLike, model: str) -> None:
        self._client = client
        self._model = model

    async def extract(self, raw_text: str) -> ExtractedLead:
        prompt = render("extract_lead", raw_text=raw_text)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        try:
            data: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as exc:
            log.warning(
                "openai_extractor.invalid_json",
                model=self._model,
                content_head=content[:200],
            )
            raise ValueError(f"OpenAI returned invalid JSON: {exc}") from exc

        return ExtractedLead(
            full_name=_str_or_none(data.get("full_name")),
            contact=_str_or_none(data.get("contact")),
            project_type=_str_or_none(data.get("project_type")),
            area_m2=_float_or_none(data.get("area_m2")),
            budget_range=_str_or_none(data.get("budget_range")),
            timeline=_str_or_none(data.get("timeline")),
            summary=_str_or_none(data.get("summary")) or "",
            confidence=_float_or_none(data.get("confidence")) or 0.0,
            raw_response=data,
        )


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
