import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.integration
async def test_engine_connects_and_runs_trivial_query(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 AS one"))
        row = result.one()
    assert row.one == 1
