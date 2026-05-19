import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from crm.adapters.ai.extractor import FakeAIExtractor
from crm.adapters.ai.proposal_writer import FakeProposalWriter
from crm.adapters.gdocs.client import FakeGDocsClient
from crm.adapters.telegram.sender import FakeTelegramSender
from crm.config import AppEnv, Settings
from crm.container import Container


def _settings(provider: str = "fake") -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env=AppEnv.test,
        log_level="INFO",
        database_url="postgresql+asyncpg://x:y@z/db",
        telegram_bot_token="t",
        telegram_operator_ids=(111,),
        ai_provider=provider,
    )


def test_container_builds_engine_and_session_factory() -> None:
    container = Container(_settings())
    assert isinstance(container.engine, AsyncEngine)
    assert isinstance(container.session_factory, async_sessionmaker)


def test_container_picks_fake_adapters_in_test_env() -> None:
    container = Container(_settings(provider="fake"))
    assert isinstance(container.ai_extractor, FakeAIExtractor)
    assert isinstance(container.proposal_writer, FakeProposalWriter)
    assert isinstance(container.gdocs, FakeGDocsClient)
    assert isinstance(container.telegram_sender, FakeTelegramSender)


def test_container_uow_can_be_constructed() -> None:
    container = Container(_settings())
    uow = container.uow()
    assert uow is not None


def test_build_ai_extractor_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm.adapters.ai.extractor import FakeAIExtractor
    from crm.config import Settings
    from crm.container import _build_ai_extractor

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "1")
    monkeypatch.setenv("AI_PROVIDER", "fake")
    settings = Settings()  # type: ignore[call-arg]

    extractor = _build_ai_extractor(settings)
    assert isinstance(extractor, FakeAIExtractor)


def test_build_ai_extractor_openai_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm.config import Settings
    from crm.container import _build_ai_extractor

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "1")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = Settings()  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _build_ai_extractor(settings)


def test_build_ai_extractor_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm.config import Settings
    from crm.container import _build_ai_extractor

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "1")
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    settings = Settings()  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="Unsupported AI_PROVIDER"):
        _build_ai_extractor(settings)
