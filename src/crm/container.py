"""Dependency injection container.

Each entrypoint (api / bot / worker) instantiates one `Container` at startup
and passes it (or its parts) to use cases. No globals.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from crm.adapters.ai.extractor import AIExtractor, FakeAIExtractor
from crm.adapters.ai.openai_extractor import OpenAIExtractor
from crm.adapters.ai.proposal_writer import FakeProposalWriter, ProposalWriter
from crm.adapters.gdocs.client import FakeGDocsClient, GDocsClient
from crm.adapters.telegram.sender import FakeTelegramSender, TelegramSender
from crm.config import Settings
from crm.db.session import build_engine, build_session_factory
from crm.db.unit_of_work import SqlAlchemyUnitOfWork


class Container:
    """Wires up application dependencies based on Settings."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker
    ai_extractor: AIExtractor
    proposal_writer: ProposalWriter
    gdocs: GDocsClient
    telegram_sender: TelegramSender

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = build_engine(settings)
        self.session_factory = build_session_factory(self.engine)

        self.ai_extractor = _build_ai_extractor(settings)
        self.proposal_writer = _build_proposal_writer(settings)
        self.gdocs = _build_gdocs(settings)
        self.telegram_sender = _build_telegram_sender(settings)

    def uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory)

    async def aclose(self) -> None:
        """Dispose of resources. Call on graceful shutdown."""
        await self.engine.dispose()


def _build_ai_extractor(settings: Settings) -> AIExtractor:
    provider = settings.ai_provider.lower()
    if provider == "openai":
        from openai import AsyncOpenAI

        if not settings.openai_api_key:
            raise RuntimeError("AI_PROVIDER=openai but OPENAI_API_KEY is not set")
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return OpenAIExtractor(client=client, model=settings.openai_model)
    if provider == "fake":
        return FakeAIExtractor()
    raise RuntimeError(f"Unsupported AI_PROVIDER: {settings.ai_provider!r}")


def _build_proposal_writer(settings: Settings) -> ProposalWriter:
    provider = settings.ai_provider.lower()
    if provider == "openai":
        from openai import AsyncOpenAI

        from crm.adapters.ai.openai_proposal_writer import OpenAIProposalWriter

        if not settings.openai_api_key:
            raise RuntimeError("AI_PROVIDER=openai but OPENAI_API_KEY is not set")
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return OpenAIProposalWriter(client=client, model=settings.openai_model)
    if provider == "fake":
        return FakeProposalWriter()
    raise RuntimeError(f"Unsupported AI_PROVIDER: {settings.ai_provider!r}")


def _build_gdocs(_settings: Settings) -> GDocsClient:
    # Real GDocs client arrives in Plan 6.
    return FakeGDocsClient()


def _build_telegram_sender(_settings: Settings) -> TelegramSender:
    # Real aiogram-backed sender arrives in Plan 3 (or here later if needed).
    return FakeTelegramSender()
