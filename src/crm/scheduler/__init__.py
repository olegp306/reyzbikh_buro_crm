"""Postgres-backed job queue.

- ``jobs.enqueue_job(uow, ...)`` — atomic enqueue (idempotency-aware).
- ``jobs.apply_backoff(attempts)`` — exponential backoff with jitter.
- ``handlers.JOB_HANDLERS`` — registry of job_type → handler.
- ``runner.run_worker(container, worker_id)`` — main poll loop.
"""
