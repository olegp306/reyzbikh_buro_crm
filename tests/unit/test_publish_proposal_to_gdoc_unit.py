"""Unit tests for publish_proposal_to_gdoc — error paths without DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.use_cases.publish_proposal_to_gdoc import (
    ProposalNotFoundError,
    ProposalNotReadyError,
    publish_proposal_to_gdoc,
)


@pytest.mark.asyncio
async def test_publish_raises_when_proposal_missing() -> None:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.proposals = MagicMock()
    uow.proposals.get = AsyncMock(return_value=None)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(ProposalNotFoundError):
        await publish_proposal_to_gdoc(container, proposal_id=1, operator_user_id=None)


@pytest.mark.asyncio
async def test_publish_raises_when_body_empty() -> None:
    proposal = MagicMock()
    proposal.id = 1
    proposal.generated_text = "   "
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.proposals = MagicMock()
    uow.proposals.get = AsyncMock(return_value=proposal)
    container = MagicMock()
    container.uow = MagicMock(return_value=uow)

    with pytest.raises(ProposalNotReadyError):
        await publish_proposal_to_gdoc(container, proposal_id=1, operator_user_id=None)
