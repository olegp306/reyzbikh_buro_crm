"""Unit tests for qualify_lead — covers status guards."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.db.models.enums import LeadStatus
from crm.use_cases.qualify_lead import (
    LeadCannotQualifyError,
    LeadNotFoundError,
    qualify_lead,
)


def _container_with_lead(lead) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.session = MagicMock()
    uow.session.add = MagicMock()
    uow.session.flush = AsyncMock()
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=lead)
    uow.clients = MagicMock()

    fake_client = MagicMock()
    fake_client.id = 555
    uow.clients.add = AsyncMock(return_value=fake_client)

    container = MagicMock()
    container.uow = MagicMock(return_value=uow)
    return container


@pytest.mark.asyncio
async def test_qualify_lead_not_found_raises() -> None:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.leads = MagicMock()
    uow.leads.get = AsyncMock(return_value=None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(LeadNotFoundError):
        await qualify_lead(container, lead_id=1, operator_user_id=None)


@pytest.mark.asyncio
async def test_qualify_lead_terminal_status_raises() -> None:
    lead = MagicMock()
    lead.id = 1
    lead.status = LeadStatus.archived
    container = _container_with_lead(lead)

    with pytest.raises(LeadCannotQualifyError):
        await qualify_lead(container, lead_id=1, operator_user_id=None)
