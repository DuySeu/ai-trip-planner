"""Provider quota blocks shared by the API and the worker."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import Connection

from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "quota.sql")


# Block a service until its quota resets, replacing any earlier block
def block(conn: Connection[Any], service: str, until: datetime, reason: str) -> None:
    conn.execute(QUERIES["block"], {"service": service, "until": until, "reason": reason})


# When the service's block ends, or None if it is not blocked now
def active_block(conn: Connection[Any], service: str) -> datetime | None:
    row = conn.execute(QUERIES["active_block"], {"service": service}).fetchone()
    return None if row is None else row[0]


# Tavily fetches since 00:00 UTC, counted from the cache rows they wrote
def count_tavily_today(conn: Connection[Any]) -> int:
    row = conn.execute(QUERIES["count_tavily_today"]).fetchone()
    assert row is not None
    return int(row[0])
