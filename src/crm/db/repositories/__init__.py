"""Repositories. One class per aggregate, hung off the Unit of Work.

Repositories are stateless wrappers over an AsyncSession. They neither commit
nor roll back — the caller (typically a use case via uow_scope) owns the
transaction boundary.
"""
