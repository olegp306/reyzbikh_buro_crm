"""Worker entrypoint — scheduled_jobs poll loop.

Single process that:
  1. Builds a Container.
  2. Registers job handlers from known modules.
  3. Runs the poll loop until SIGTERM / SIGINT.
"""

from __future__ import annotations

import asyncio
import signal
import socket
import uuid

import structlog

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging
from crm.scheduler.runner import run_worker

log = structlog.get_logger(__name__)


def _register_all_handlers() -> None:
    """Centralised handler registration.

    Add ``register_handler(job_type, fn)`` calls here as new job types
    are introduced.
    """
    from crm.scheduler.handlers import register_handler
    from crm.use_cases.publish_proposal_to_gdoc import (
        JOB_TYPE_PUBLISH_PROPOSAL,
        handle_publish_proposal_to_gdoc,
    )
    from crm.use_cases.send_follow_up import (
        JOB_TYPE_SEND_FOLLOW_UP,
        handle_send_follow_up,
    )

    register_handler(JOB_TYPE_PUBLISH_PROPOSAL, handle_publish_proposal_to_gdoc)
    register_handler(JOB_TYPE_SEND_FOLLOW_UP, handle_send_follow_up)


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)

    _register_all_handlers()

    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, sig_name), shutdown.set)
        except (NotImplementedError, AttributeError):
            # Windows / unsupported platforms — CTRL-C still raises KeyboardInterrupt.
            pass

    try:
        await run_worker(container, worker_id=worker_id, shutdown=shutdown)
    finally:
        await container.aclose()
        log.info("worker.entrypoint.stopped", worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(run())
