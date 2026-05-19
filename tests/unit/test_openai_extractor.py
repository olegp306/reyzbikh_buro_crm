"""Unit tests for OpenAIExtractor with a mocked AsyncOpenAI client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.openai_extractor import OpenAIExtractor


def _completion_response(payload: dict) -> SimpleNamespace:
    """Build a minimal openai SDK-shaped response object."""
    msg = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice], model="gpt-5.5-medium")


@pytest.mark.asyncio
async def test_extract_parses_structured_json_response() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_completion_response(
            {
                "full_name": "Иван",
                "contact": "+7900xxx",
                "project_type": "house",
                "area_m2": 200,
                "budget_range": "3 млн",
                "timeline": "к маю",
                "summary": "Дом 200 м2, бюджет 3 млн, срок май.",
                "confidence": 0.85,
            }
        )
    )

    extractor = OpenAIExtractor(client=client, model="gpt-5.5-medium")
    result = await extractor.extract("Иван, дом 200 м2, бюджет 3 млн, к маю")

    assert result.full_name == "Иван"
    assert result.area_m2 == 200
    assert result.summary.startswith("Дом")
    assert result.confidence == 0.85
    assert "full_name" in result.raw_response
    client.chat.completions.create.assert_awaited_once()
    call = client.chat.completions.create.await_args
    assert call.kwargs["model"] == "gpt-5.5-medium"
    assert call.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_extract_tolerates_missing_optional_fields() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_completion_response(
            {
                "summary": "Ремонт без деталей.",
                "confidence": 0.4,
            }
        )
    )

    extractor = OpenAIExtractor(client=client, model="gpt-5.5-medium")
    result = await extractor.extract("Ремонт")

    assert result.full_name is None
    assert result.area_m2 is None
    assert result.summary == "Ремонт без деталей."
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_extract_invalid_json_raises_value_error() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    choice = SimpleNamespace(message=SimpleNamespace(content="not json"))
    response = SimpleNamespace(choices=[choice], model="gpt-5.5-medium")
    client.chat.completions.create = AsyncMock(return_value=response)

    extractor = OpenAIExtractor(client=client, model="gpt-5.5-medium")

    with pytest.raises(ValueError, match="invalid JSON"):
        await extractor.extract("anything")
