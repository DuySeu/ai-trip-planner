"""Messages of a conversation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from core.exceptions import NotFound
from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "messages.sql")


# One row of messages; metadata is the structured part of a reply (cards, form or card state)
@dataclass(frozen=True)
class MessageRow:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    intent: str | None
    metadata: dict[str, Any] | None
    created_at: datetime


# Append a message to a conversation
def add_message(
    conn: Connection[Any],
    conversation_id: UUID,
    role: str,
    content: str,
    intent: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MessageRow:
    params = {
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "intent": intent,
        "metadata": None if metadata is None else Jsonb(dict(metadata)),
    }
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        row = cur.execute(QUERIES["add_message"], params).fetchone()
    assert row is not None  # INSERT ... RETURNING always returns the row
    return row


# Fetch a message by id
def get_message(conn: Connection[Any], message_id: UUID, lock: bool = False) -> MessageRow:
    query = QUERIES["lock_message" if lock else "get_message"]
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        row = cur.execute(query, {"id": message_id}).fetchone()
    if row is None:
        raise NotFound(f"message {message_id}")
    return row


# Replace the metadata while it still holds every key of expect (an open form, an open card);
# None when it already moved on
def update_open_metadata(
    conn: Connection[Any],
    message_id: UUID,
    expect: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> MessageRow | None:
    params = {"id": message_id, "expect": Jsonb(dict(expect)), "metadata": Jsonb(dict(metadata))}
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        return cur.execute(QUERIES["update_open_metadata"], params).fetchone()


# The newest questionnaire card of the conversation that is still open, if any
def find_open_questionnaire(conn: Connection[Any], conversation_id: UUID) -> MessageRow | None:
    params = {"conversation_id": conversation_id}
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        return cur.execute(QUERIES["find_open_questionnaire"], params).fetchone()


# The last `limit` messages, oldest first
def recent_messages(conn: Connection[Any], conversation_id: UUID, limit: int) -> list[MessageRow]:
    params = {"conversation_id": conversation_id, "limit": limit}
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        return cur.execute(QUERIES["recent_messages"], params).fetchall()


# One page of messages, oldest first
def list_messages(
    conn: Connection[Any], conversation_id: UUID, limit: int, offset: int
) -> list[MessageRow]:
    params = {"conversation_id": conversation_id, "limit": limit, "offset": offset}
    with conn.cursor(row_factory=class_row(MessageRow)) as cur:
        return cur.execute(QUERIES["list_messages"], params).fetchall()


# How many messages the conversation holds
def count_messages(conn: Connection[Any], conversation_id: UUID) -> int:
    row = conn.execute(QUERIES["count_messages"], {"conversation_id": conversation_id}).fetchone()
    assert row is not None
    return int(row[0])


# Messages the user sent since midnight in Vietnam, over all their conversations
def count_user_messages_today(conn: Connection[Any], user_id: UUID) -> int:
    row = conn.execute(QUERIES["count_user_messages_today"], {"user_id": user_id}).fetchone()
    assert row is not None
    return int(row[0])
