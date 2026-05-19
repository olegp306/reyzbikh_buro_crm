import io
import json
import logging

import pytest
import structlog

from crm.config import AppEnv, Settings
from crm.logging import configure_logging, mask_secrets


def _make_settings(app_env: AppEnv) -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env=app_env,
        log_level="DEBUG",
        database_url="postgresql+asyncpg://x:y@z/db",
        telegram_bot_token="t",
        telegram_operator_ids=(1,),
        ai_provider="fake",
    )


def test_mask_secrets_redacts_known_keys() -> None:
    event = {
        "msg": "hi",
        "api_key": "sk-secret",
        "telegram_bot_token": "12345:abc",
        "user_id": 42,
    }
    masked = mask_secrets(None, "info", event.copy())
    assert masked["api_key"] == "***"
    assert masked["telegram_bot_token"] == "***"
    assert masked["user_id"] == 42
    assert masked["msg"] == "hi"


def test_configure_logging_prod_emits_json(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    configure_logging(_make_settings(AppEnv.prod))

    log = structlog.get_logger("test")
    log.info("hello", lead_id=42, api_key="should-mask")

    line = buffer.getvalue().strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["lead_id"] == 42
    assert record["api_key"] == "***"


def test_configure_logging_dev_is_human_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    configure_logging(_make_settings(AppEnv.dev))

    log = structlog.get_logger("test")
    log.info("hello", lead_id=42)

    output = buffer.getvalue()
    assert "hello" in output
    assert "lead_id" in output
    # Dev format is not valid JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.strip().splitlines()[-1])


def test_configure_logging_sets_stdlib_level() -> None:
    configure_logging(_make_settings(AppEnv.dev))
    assert logging.getLogger().level == logging.DEBUG
