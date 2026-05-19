"""send_follow_up use case + worker handler.

Spec §5.1 steps 22-23. The worker calls ``handle_send_follow_up`` which
delegates to ``send_follow_up``. The use case sends a Telegram reminder
to the operator with an inline keyboard for recording the outcome,
then marks the FollowUp as sent.

Idempotency: if the FollowUp is not in ``pending`` status (e.g. already
``sent`` from a previous attempt) the use case is a no-op. The
underlying lease-reclaim retry path therefore can't double-notify.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from crm.db.models.enums import FollowUpStatus
from crm.db.models.scheduled_job import ScheduledJob
from crm.use_cases.events import record_event

if TYPE_CHECKING:
    from crm.container import Container
    from crm.db.models.follow_up import FollowUp

log = structlog.get_logger(__name__)

JOB_TYPE_SEND_FOLLOW_UP = "send_follow_up"

# Outcome callback prefix — exported so the bot's callback router can
# pattern-match the same string without drifting. The keyboard builder
# below uses it directly.
FOLLOW_UP_OUTCOME_PREFIX = "follow_up_outcome:"


class FollowUpNotFoundError(LookupError):
    """No follow-up with the requested id."""


def _outcome_keyboard(follow_up_id: int):
    """Build the inline keyboard for the operator to record the outcome.

    Imported lazily so use cases don't pull aiogram at module top.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принял",
                    callback_data=f"{FOLLOW_UP_OUTCOME_PREFIX}{follow_up_id}:accepted",
                ),
                InlineKeyboardButton(
                    text="❌ Отказался",
                    callback_data=f"{FOLLOW_UP_OUTCOME_PREFIX}{follow_up_id}:declined",
                ),
                InlineKeyboardButton(
                    text="💬 Жду",
                    callback_data=f"{FOLLOW_UP_OUTCOME_PREFIX}{follow_up_id}:waiting",
                ),
            ],
        ],
    )


async def send_follow_up(
    container: Container,
    *,
    follow_up_id: int,
) -> FollowUp:
    """Send the reminder message + mark the FollowUp as sent."""
    async with container.uow() as uow:
        follow_up = await uow.follow_ups.get(follow_up_id)
        if follow_up is None:
            raise FollowUpNotFoundError(f"FollowUp {follow_up_id} not found")
        if follow_up.status != FollowUpStatus.pending:
            log.info(
                "send_follow_up.skip_non_pending",
                follow_up_id=follow_up_id,
                status=follow_up.status.value,
            )
            return follow_up
        message_text = follow_up.message_template

    # Send the reminder OUTSIDE the DB transaction.
    ids = container.settings.telegram_operator_ids
    if not ids:
        log.warning(
            "send_follow_up.no_operator_configured",
            follow_up_id=follow_up_id,
        )
    else:
        chat_id = ids[0]
        try:
            await container.telegram_sender.send_message(
                chat_id=chat_id,
                text=message_text,
                reply_markup=_outcome_keyboard(follow_up_id),
            )
        except Exception as exc:
            # Re-raise so the worker reschedules with backoff.
            log.warning(
                "send_follow_up.send_failed",
                follow_up_id=follow_up_id,
                error=str(exc),
            )
            raise

    now = datetime.now(UTC)
    async with container.uow() as uow:
        follow_up = await uow.follow_ups.get(follow_up_id)
        if follow_up is None:
            raise RuntimeError(f"send_follow_up: FollowUp {follow_up_id} disappeared after notify")
        # Double-check no other worker raced us between the notify and this TX.
        if follow_up.status != FollowUpStatus.pending:
            log.info(
                "send_follow_up.race_after_notify",
                follow_up_id=follow_up_id,
                status=follow_up.status.value,
            )
            return follow_up
        follow_up.status = FollowUpStatus.sent
        follow_up.sent_at = now
        await record_event(
            uow,
            event_type="follow_up.sent",
            aggregate_type="follow_up",
            aggregate_id=follow_up_id,
            payload={"sent_at": now.isoformat()},
            actor_user_id=None,
        )
        await uow.commit()
        result = follow_up

    log.info("send_follow_up.done", follow_up_id=follow_up_id)
    return result


async def handle_send_follow_up(container: Container, job: ScheduledJob) -> None:
    """Worker handler — thin shim that delegates to ``send_follow_up``."""
    follow_up_id = int(job.payload["follow_up_id"])
    await send_follow_up(container, follow_up_id=follow_up_id)
