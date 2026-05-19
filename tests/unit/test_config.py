import pytest
from pydantic import ValidationError

from crm.config import AppEnv, Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://crm:crm@localhost:5432/crm",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "111,222,333")
    monkeypatch.setenv("AI_PROVIDER", "fake")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.app_env is AppEnv.test
    assert settings.log_level == "DEBUG"
    assert settings.telegram_operator_ids == (111, 222, 333)
    assert settings.ai_provider == "fake"


def test_settings_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "APP_ENV",
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OPERATOR_IDS",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_operator_id_allowlist_parses_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@z/db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "")
    monkeypatch.setenv("AI_PROVIDER", "fake")

    settings = Settings()  # type: ignore[call-arg]
    assert settings.telegram_operator_ids == ()
