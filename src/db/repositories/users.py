"""Users: claim a name, look one up."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import class_row

from core.exceptions import NotFound
from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "users.sql")


# One row of users
@dataclass(frozen=True)
class UserRow:
    id: UUID
    name: str
    name_key: str
    created_at: datetime
    last_seen_at: datetime | None


# Insert the name, or return the user who already holds it; the caller NFC-normalizes the name
def claim_user(conn: Connection[Any], name: str) -> UserRow:
    with conn.cursor(row_factory=class_row(UserRow)) as cur:
        row = cur.execute(QUERIES["claim_user"], {"name": name}).fetchone()
    assert row is not None  # INSERT ... ON CONFLICT DO UPDATE always returns the row
    return row


# Fetch a user by id
def get_user(conn: Connection[Any], user_id: UUID) -> UserRow:
    with conn.cursor(row_factory=class_row(UserRow)) as cur:
        row = cur.execute(QUERIES["get_user"], {"id": user_id}).fetchone()
    if row is None:
        raise NotFound(f"user {user_id}")
    return row
