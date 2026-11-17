"""Search cache and the research rows plans cite as sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "research.sql")


# One source to save; title, url and snippet are what the LLM saw
@dataclass(frozen=True)
class SourceInput:
    title: str | None
    url: str | None
    snippet: str | None
    cache_key: str | None = None


# One row of research_results; id is the source_id plans cite
@dataclass(frozen=True)
class SourceRow:
    id: int
    trip_id: UUID | None
    conversation_id: UUID | None
    kind: str
    cache_key: str | None
    title: str | None
    url: str | None
    snippet: str | None
    created_at: datetime


# The cached payload for key, or None if missing or expired
def cache_get(conn: Connection[Any], key: str) -> dict[str, Any] | None:
    row = conn.execute(QUERIES["cache_get"], {"key": key}).fetchone()
    return None if row is None else row[0]


# Store a provider response for ttl, replacing any older row with the same key
def cache_put(
    conn: Connection[Any],
    key: str,
    provider: str,
    query: str,
    payload: Mapping[str, Any],
    ttl: timedelta,
) -> None:
    params = {
        "key": key,
        "provider": provider,
        "query": query,
        "payload": Jsonb(payload),
        "ttl": ttl,
    }
    conn.execute(QUERIES["cache_put"], params)


# Save sources owned by a trip or by a discovery conversation (exactly one of the two)
def save_sources(
    conn: Connection[Any],
    *,
    trip_id: UUID | None = None,
    conversation_id: UUID | None = None,
    kind: str,
    items: Sequence[SourceInput],
) -> list[SourceRow]:
    saved = []
    with conn.cursor(row_factory=class_row(SourceRow)) as cur:
        for item in items:
            params = {
                "trip_id": trip_id,
                "conversation_id": conversation_id,
                "kind": kind,
                "cache_key": item.cache_key,
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
            }
            row = cur.execute(QUERIES["save_source"], params).fetchone()
            assert row is not None  # INSERT ... RETURNING always returns the row
            saved.append(row)
    return saved


# A trip's sources in the order they were saved
def sources_for_trip(conn: Connection[Any], trip_id: UUID) -> list[SourceRow]:
    with conn.cursor(row_factory=class_row(SourceRow)) as cur:
        return cur.execute(QUERIES["sources_for_trip"], {"trip_id": trip_id}).fetchall()
