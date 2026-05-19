"""Application settings loaded from environment variables via pydantic-settings."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnv(StrEnum):
    dev = "dev"
    test = "test"
    prod = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: AppEnv = Field(...)
    log_level: str = Field(default="INFO")

    database_url: str = Field(...)

    telegram_bot_token: str = Field(...)
    # NoDecode prevents pydantic-settings >=2.7 from JSON-decoding the env
    # value before our @field_validator runs; without it,
    # `TELEGRAM_OPERATOR_IDS=111,222` would fail JSON parsing.
    telegram_operator_ids: Annotated[tuple[int, ...], NoDecode] = Field(...)

    ai_provider: Literal["openai", "anthropic", "fake"] = Field(default="fake")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-5.5-medium")

    google_service_account_json: str | None = Field(default=None)
    google_docs_parent_folder_id: str | None = Field(default=None)

    worker_poll_interval_seconds: float = Field(default=5.0)

    @field_validator("telegram_operator_ids", mode="before")
    @classmethod
    def _parse_operator_ids(cls, raw: object) -> tuple[int, ...]:
        if raw is None or raw == "":
            return ()
        if isinstance(raw, str):
            return tuple(int(p.strip()) for p in raw.split(",") if p.strip())
        if isinstance(raw, (list, tuple)):
            return tuple(int(p) for p in raw)
        msg = f"Cannot parse telegram_operator_ids from {raw!r}"
        raise ValueError(msg)
