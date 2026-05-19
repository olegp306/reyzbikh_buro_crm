"""ORM models. Imported by Alembic env.py for autogenerate.

Add every new model class to this re-export so Alembic sees it.
"""

from crm.db.models.client import Client
from crm.db.models.user import User

__all__ = ["Client", "User"]
