"""Worker entrypoint.

In Plan 1 this is a heartbeat loop only — no job dispatching yet.
Plan 5 expands it into the real Postgres-backed scheduler.
"""

from __future__ import annotations

import asyncio
import signal

import structlog

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging

log = structlog.get_logger(__name__)


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)

    stop = asyncio.Event()

    def _request_stop() -> None:
        log.info("worker.stop_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows: signals not supported in proactor loop. Fine for dev.
            pass

    log.info(
        "worker.starting",
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )
    try:
        while not stop.is_set():
            log.debug("worker.heartbeat")
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.worker_poll_interval_seconds,
                )
            except TimeoutError:
                continue
    finally:
        await container.aclose()
        log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(run())
