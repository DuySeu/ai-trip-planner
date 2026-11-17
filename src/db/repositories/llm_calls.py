"""Log of every LLM call, for quota ceilings, model health and debugging."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection

from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "llm_calls.sql")


# One LLM call's outcome; no prompt or response text (privacy)
@dataclass(frozen=True)
class LlmCallRecord:
    purpose: str
    model_id: str
    outcome: str
    trip_id: UUID | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None


# Store one call
def log_call(conn: Connection[Any], record: LlmCallRecord) -> None:
    conn.execute(QUERIES["log_call"], asdict(record))


# Calls since 00:00 UTC, optionally only for some purposes
def count_today(conn: Connection[Any], purpose_in: Sequence[str] | None = None) -> int:
    purposes = None if purpose_in is None else list(purpose_in)
    row = conn.execute(QUERIES["count_today"], {"purposes": purposes}).fetchone()
    assert row is not None
    return int(row[0])
