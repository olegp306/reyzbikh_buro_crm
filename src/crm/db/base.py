"""SQLAlchemy declarative base for all ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base for every ORM model.

    All ORM models in `crm.db.models.*` must inherit from this class
    so that Alembic autogeneration sees them.
    """
