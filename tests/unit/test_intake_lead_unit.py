"""Unit tests for intake_lead — verifies the use case wires its parts
together without booting a real database."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.adapters.ai.extractor import ExtractedLead
from crm.db.models.enums import ChannelKind, LeadStatus
from crm.use_cases.intake_lead import intake_lead


def _stub_lead(lead_id: int = 1) -> MagicMock:
    lead = MagicMock()
    lead.id = lead_id
    lead.status = LeadStatus.new
    lead.extracted_data = {}
    lead.summary = None
    return lead


@pytest.mark.asyncio
async def test_intake_lead_calls_ai_outside_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    lead = _stub_lead()

    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.leads = MagicMock()
    uow.leads.add = AsyncMock(return_value=lead)
    uow.leads.get = AsyncMock(return_value=lead)

    container = MagicMock()
    container.uow = MagicMock(return_value=uow)
    container.ai_extractor = MagicMock()
    container.ai_extractor.extract = AsyncMock(
        return_value=ExtractedLead(summary="ok", confidence=0.8, raw_response={"k": "v"})
    )

    result = await intake_lead(
        container,
        raw_text="hello",
        channel=ChannelKind.telegram,
        channel_message_id="tg:1",
        operator_user_id=42,
    )

    assert result.status == LeadStatus.qualifying
    assert result.summary == "ok"
    assert result.extracted_data == {"k": "v"}
    container.ai_extractor.extract.assert_awaited_once_with("hello")
    assert uow.commit.await_count == 2
