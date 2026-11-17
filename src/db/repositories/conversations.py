"""Conversations: create, list, keep the trip draft."""

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

QUERIES = load_queries(QUERIES_DIR / "conversations.sql")


# One row of conversations
@dataclass(frozen=True)
class ConversationRow:
    id: UUID
    user_id: UUID
    title: str | None
    request_draft: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# Start a conversation, optionally with trip fields already gathered
def create_conversation(
    conn: Connection[Any], user_id: UUID, draft: Mapping[str, Any] | None
) -> ConversationRow:
    params = {"user_id": user_id, "draft": None if draft is None else Jsonb(draft)}
    with conn.cursor(row_factory=class_row(ConversationRow)) as cur:
        row = cur.execute(QUERIES["create_conversation"], params).fetchone()
    assert row is not None  # INSERT ... RETURNING always returns the row
    return row


# Fetch a conversation by id
def get_conversation(conn: Connection[Any], conversation_id: UUID) -> ConversationRow:
    with conn.cursor(row_factory=class_row(ConversationRow)) as cur:
        row = cur.execute(QUERIES["get_conversation"], {"id": conversation_id}).fetchone()
    if row is None:
        raise NotFound(f"conversation {conversation_id}")
    return row


# A user's conversations, most recently active first
def list_conversations(conn: Connection[Any], user_id: UUID) -> list[ConversationRow]:
    with conn.cursor(row_factory=class_row(ConversationRow)) as cur:
        return cur.execute(QUERIES["list_conversations"], {"user_id": user_id}).fetchall()


# Replace the trip draft gathered so far
def save_draft(conn: Connection[Any], conversation_id: UUID, draft: Mapping[str, Any]) -> None:
    params = {"id": conversation_id, "draft": Jsonb(draft)}
    if conn.execute(QUERIES["save_draft"], params).rowcount == 0:
        raise NotFound(f"conversation {conversation_id}")


# Mark the conversation as active now
def touch_conversation(conn: Connection[Any], conversation_id: UUID) -> None:
    if conn.execute(QUERIES["touch_conversation"], {"id": conversation_id}).rowcount == 0:
        raise NotFound(f"conversation {conversation_id}")
