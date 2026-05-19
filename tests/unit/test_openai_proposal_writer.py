"""Unit tests for OpenAIProposalWriter with a mocked AsyncOpenAI client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.openai_proposal_writer import OpenAIProposalWriter


def _resp(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        model="gpt-5.5-medium",
    )


@pytest.mark.asyncio
async def test_generate_parses_full_payload() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_resp(
            {
                "body": "Здравствуйте! Спасибо за обращение. ...",
                "scope_summary": "Ремонт квартиры 60 м2",
                "price_estimate": 350000,
                "currency": "RUB",
            }
        )
    )

    writer = OpenAIProposalWriter(client=client, model="gpt-5.5-medium")
    draft = await writer.generate(
        lead_summary="renovation",
        extracted={"area_m2": 60},
    )

    assert draft.body.startswith("Здравствуйте")
    assert draft.scope_summary.startswith("Ремонт")
    assert draft.price_estimate == 350000
    assert draft.currency == "RUB"

    call = client.chat.completions.create.await_args
    assert call.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_generate_tolerates_missing_price() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_resp(
            {
                "body": "Привет!",
                "scope_summary": "scope",
                "currency": "RUB",
            }
        )
    )

    writer = OpenAIProposalWriter(client=client, model="gpt-5.5-medium")
    draft = await writer.generate(lead_summary="x", extracted={})

    assert draft.price_estimate is None
    assert draft.currency == "RUB"


@pytest.mark.asyncio
async def test_generate_invalid_json_raises() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    bad = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="garbage"))],
        model="gpt-5.5-medium",
    )
    client.chat.completions.create = AsyncMock(return_value=bad)

    writer = OpenAIProposalWriter(client=client, model="gpt-5.5-medium")

    with pytest.raises(ValueError, match="invalid JSON"):
        await writer.generate(lead_summary="x", extracted={})
