"""Postgres-backed sink for the model router: call log and provider quota blocks."""

from __future__ import annotations

from datetime import datetime

from psycopg_pool import ConnectionPool

from db.repositories import quota
from db.repositories.llm_calls import LlmCallRecord, log_call


# Each method runs in its own short transaction, so a failed job never rolls back its call log
class DbCallSink:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # Store one call's outcome
    def log(self, record: LlmCallRecord) -> None:
        with self._pool.connection() as conn:
            log_call(conn, record)

    # Block a service until its quota resets
    def block(self, service: str, until: datetime, reason: str) -> None:
        with self._pool.connection() as conn:
            quota.block(conn, service, until, reason)

    # When the service's block ends, or None if it is not blocked now
    def blocked_until(self, service: str) -> datetime | None:
        with self._pool.connection() as conn:
            return quota.active_block(conn, service)
