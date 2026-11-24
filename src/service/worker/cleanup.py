"""Daily retention cleanup: idle users and expired cache rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from psycopg import Connection

from db.queries import QUERIES_DIR, load_queries

USER_QUERIES = load_queries(QUERIES_DIR / "users.sql")
RESEARCH_QUERIES = load_queries(QUERIES_DIR / "research.sql")


# How many rows one cleanup run deleted
@dataclass(frozen=True)
class CleanupCounts:
    conversations: int
    users: int
    cache_rows: int


# Delete users with no trips idle for user_inactive_days, and expired cache rows
def run_cleanup(conn: Connection[Any], now: datetime, user_inactive_days: int) -> CleanupCounts:
    # One transaction, so a failure leaves everything as it was
    with conn.transaction():
        cutoff = now - timedelta(days=user_inactive_days)
        row = conn.execute(USER_QUERIES["delete_idle_users"], {"cutoff": cutoff}).fetchone()
        assert row is not None  # the final SELECT always returns one row

        cache_rows = conn.execute(RESEARCH_QUERIES["delete_expired_cache"], {"now": now}).rowcount

    return CleanupCounts(conversations=row[1], users=row[0], cache_rows=cache_rows)
