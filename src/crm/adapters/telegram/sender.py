"""Telegram outbound message sender."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SentMessage:
    """Record of an outbound Telegram message."""

    chat_id: int
    text: str


class TelegramSender(Protocol):
    """Sends a Telegram message to a chat."""

    async def send_message(self, *, chat_id: int, text: str) -> None: ...


@dataclass
class FakeTelegramSender:
    """In-memory sender that records every outgoing message."""

    sent: list[SentMessage] = field(default_factory=list)

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.sent.append(SentMessage(chat_id=chat_id, text=text))
