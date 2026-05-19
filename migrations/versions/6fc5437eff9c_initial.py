"""initial

Revision ID: 6fc5437eff9c
Revises:
Create Date: 2026-05-19 19:07:19.741990

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401

revision: str = "6fc5437eff9c"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: the schema is built up in later migrations."""


def downgrade() -> None:
    """No-op."""
