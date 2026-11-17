"""Messages of a conversation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "messages.sql")


# One row of messages; suggestions is the raw JSONB array of destination cards
@dataclass(frozen=True)
class MessageRow:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    intent: str | None
    suggestions: list[Any] | None
    created_at: datetime


# Append a message to a conversation
def add_message(
    conn: Connection[Any],
    conversation_id: UUID,
    role: str,
    content: str,
    intent: str | None = None,
    suggestions: Sequence[Any] | None = None,
) -> MessageRow:
    params = {
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "intent": intent,
        "suggestions": None if suggestions is None else Jsonb(list(suggestions)),
    }
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        row = cur.execute(QUERIES["add_message"], params).fetchone()
    assert row is not None  # INSERT ... RETURNING always returns the row
    return row


# The last `limit` messages, oldest first
def recent_messages(conn: Connection[Any], conversation_id: UUID, limit: int) -> list[MessageRow]:
    params = {"conversation_id": conversation_id, "limit": limit}
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        return cur.execute(QUERIES["recent_messages"], params).fetchall()


# Messages the user sent since midnight in Vietnam, over all their conversations
def count_user_messages_today(conn: Connection[Any], user_id: UUID) -> int:
    row = conn.execute(QUERIES["count_user_messages_today"], {"user_id": user_id}).fetchone()
    assert row is not None
    return int(row[0])


# Messages in the conversation with this intent
def count_intent(conn: Connection[Any], conversation_id: UUID, intent: str) -> int:
    params = {"conversation_id": conversation_id, "intent": intent}
    row = conn.execute(QUERIES["count_intent"], params).fetchone()
    assert row is not None
    return int(row[0])
