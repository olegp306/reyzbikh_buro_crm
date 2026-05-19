"""OpenAI implementation of the ProposalWriter protocol."""

from __future__ import annotations

import json
from typing import Any, Protocol

import structlog

from crm.adapters.ai.proposal_writer import ProposalDraft
from crm.prompts import render

log = structlog.get_logger(__name__)


class _OpenAIClientLike(Protocol):
    chat: Any


class OpenAIProposalWriter:
    """Generates a proposal draft via OpenAI."""

    def __init__(self, *, client: _OpenAIClientLike, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(self, *, lead_summary: str, extracted: dict) -> ProposalDraft:
        prompt = render(
            "generate_proposal",
            lead_summary=lead_summary,
            extracted_json=json.dumps(extracted, ensure_ascii=False),
        )
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
                "openai_proposal_writer.invalid_json",
                model=self._model,
                content_head=content[:200],
            )
            raise ValueError(f"OpenAI returned invalid JSON: {exc}") from exc

        return ProposalDraft(
            body=str(data.get("body") or ""),
            scope_summary=str(data.get("scope_summary") or ""),
            price_estimate=_float_or_none(data.get("price_estimate")),
            currency=str(data.get("currency") or "RUB"),
        )


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
