"""Use cases — the single home of business logic.

Each module exposes one async function with explicit dependencies (UoW +
adapters). Bot handlers, API endpoints, and the worker all call into here.
"""
