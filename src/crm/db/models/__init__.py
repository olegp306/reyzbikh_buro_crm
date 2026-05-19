"""ORM models. Imported by Alembic env.py for autogenerate.

Add every new model class to this re-export so Alembic sees it.
"""

from crm.db.models.client import Client
from crm.db.models.contract import Contract
from crm.db.models.document import Document
from crm.db.models.follow_up import FollowUp
from crm.db.models.lead import Lead
from crm.db.models.project import Project
from crm.db.models.proposal import Proposal
from crm.db.models.user import User

__all__ = [
    "Client",
    "Contract",
    "Document",
    "FollowUp",
    "Lead",
    "Project",
    "Proposal",
    "User",
]
