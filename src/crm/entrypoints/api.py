"""FastAPI HTTP entrypoint.

In Plan 1 the only route is `/healthz`. Future plans add domain endpoints
(or alternatively, a web dashboard backend).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from crm.config import Settings
from crm.container import Container
from crm.logging import configure_logging

log = structlog.get_logger(__name__)


def build_app(container: Container) -> FastAPI:
    """Build a FastAPI app wired to the given container.

    Exposed as a factory so tests can pass test-scoped containers.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("api.starting", app_env=container.settings.app_env.value)
        try:
            yield
        finally:
            await container.aclose()
            log.info("api.shutting_down")

    app = FastAPI(title="reyzbikh-buro-crm", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        db_status = "ok"
        http_status = 200
        try:
            async with container.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"
            http_status = 503
        body = {
            "status": "ok" if db_status == "ok" else "degraded",
            "db": db_status,
        }
        return JSONResponse(content=body, status_code=http_status)

    return app


def main() -> FastAPI:
    """Factory used by `uvicorn crm.entrypoints.api:main --factory`.

    Builds a long-lived container from environment settings.
    Never invoked at import time, so test collection is safe even when env
    vars are not set.
    """
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings)
    container = Container(settings)
    return build_app(container)
