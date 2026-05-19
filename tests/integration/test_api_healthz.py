import pytest
from httpx import ASGITransport, AsyncClient

from crm.config import Settings
from crm.container import Container
from crm.entrypoints.api import build_app


@pytest.mark.integration
async def test_healthz_returns_ok_with_real_postgres(settings: Settings) -> None:
    container = Container(settings)
    app = build_app(container)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "db": "ok"}

    await container.aclose()


@pytest.mark.integration
async def test_healthz_reports_db_failure_when_db_unreachable() -> None:
    bad_settings = Settings(  # type: ignore[call-arg]
        app_env="test",  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://nope:nope@127.0.0.1:1/none",
        telegram_bot_token="t",
        telegram_operator_ids=(1,),
        ai_provider="fake",
    )
    container = Container(bad_settings)
    app = build_app(container)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"

    await container.aclose()
