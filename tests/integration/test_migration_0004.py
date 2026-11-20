"""Migration 0004 maps the messages saved under the old intents to the new intents and metadata."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from scripts.migrate import apply_migrations
from tests.integration.conftest import MIGRATIONS

SCHEMA = "mig0004"
TRIP_ID = "6f1c2b9e-0d4a-4c1e-9a51-3b7e2f0a1c01"
CARD = {"name": "Đà Lạt", "country_code": "VN"}
HOTEL = {"name": "Mercure", "source_id": 1, "url": "https://www.booking.com/x"}


# A connection whose search_path is a fresh schema migrated up to 0003
@pytest.fixture
def old_db(migrated_db: str, tmp_path: Path) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        conn.execute(f"SET search_path TO {SCHEMA}")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.stem < "0004":
                shutil.copy(path, tmp_path / path.name)
        apply_migrations(conn, tmp_path)
        try:
            yield conn
        finally:
            conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")


# Insert an assistant message the way the old code saved it; return its id
def _old(conn: psycopg.Connection, conv: Any, intent: str, content: str, cards: Any = None) -> Any:
    row = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, intent, suggestions) "
        "VALUES (%s, 'assistant', %s, %s, %s) RETURNING id",
        (conv, content, intent, None if cards is None else json.dumps(cards)),
    ).fetchone()
    assert row is not None
    return row[0]


def test_old_intents_map_to_new_intents_and_metadata(old_db, tmp_path):
    user = old_db.execute("INSERT INTO users (name) VALUES ('Duy') RETURNING id").fetchone()
    assert user is not None
    conv = old_db.execute(
        "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (user[0],)
    ).fetchone()
    assert conv is not None
    c = conv[0]
    ids = {
        "travel_advice": _old(old_db, c, "travel_advice", "Pack a jacket."),
        "answer": _old(old_db, c, "answer", "No visa needed."),
        "plan_answer": _old(old_db, c, "plan_answer", "Day 2 is the lake."),
        "trip_research": _old(old_db, c, "trip_research", "Found events."),
        "clarification": _old(old_db, c, "clarification", "Which trip?"),
        "plan_editor": _old(old_db, c, "plan_editor", "Changed."),
        "ask": _old(old_db, c, "ask", "Bạn đi khi nào?"),
        "suggest": _old(old_db, c, "suggest", "Ideas.", [CARD]),
        "hotel_options": _old(old_db, c, "hotel_options", "Hotels.", [HOTEL]),
        "hotel_no_cards": _old(old_db, c, "hotel_options", "None found."),
        "trip_form": _old(old_db, c, "trip_form", '{"origin": "Hà Nội"}'),
        "created_trip": _old(
            old_db, c, "created_trip", json.dumps({"origin": "Hà Nội", "trip_id": TRIP_ID})
        ),
        "canceled_trip": _old(old_db, c, "canceled_trip", '{"origin": "Huế"}'),
    }

    shutil.copy(MIGRATIONS / "0004_chat_intent_redesign.sql", tmp_path)
    assert apply_migrations(old_db, tmp_path) == ["0004_chat_intent_redesign"]

    def after(key: str) -> tuple[Any, ...]:
        row = old_db.execute(
            "SELECT intent, metadata, content FROM messages WHERE id = %s", (ids[key],)
        ).fetchone()
        assert row is not None
        return tuple(row)

    assert after("travel_advice") == ("advice", None, "Pack a jacket.")
    assert after("answer")[:2] == ("advice", None)
    assert after("plan_answer")[:2] == ("advice", None)
    assert after("trip_research")[:2] == ("advice", {"searched": True})
    assert after("clarification")[:2] == ("advice", {"clarify": True})
    assert after("plan_editor")[:2] == ("edit_plan", None)
    assert after("ask") == (
        "discover",
        {"kind": "questionnaire", "status": "done", "step": 0, "answers": {}, "choices": {}},
        "Bạn đi khi nào?",
    )
    assert after("suggest")[:2] == ("discover", {"kind": "suggestions", "cards": [CARD]})
    hotel = {"kind": "hotel", "status": "results", "query": "", "dates": None}
    assert after("hotel_options")[:2] == ("booking_search", {**hotel, "cards": [HOTEL]})
    assert after("hotel_no_cards")[:2] == ("booking_search", {**hotel, "cards": []})
    assert after("trip_form") == (
        "create_trip",
        {"status": "open", "draft": {"origin": "Hà Nội"}, "trip_id": None},
        "",
    )
    assert after("created_trip") == (
        "create_trip",
        {"status": "created", "draft": {"origin": "Hà Nội"}, "trip_id": TRIP_ID},
        "",
    )
    assert after("canceled_trip")[:2] == (
        "create_trip",
        {"status": "canceled", "draft": {"origin": "Huế"}, "trip_id": None},
    )
