from __future__ import annotations

import unicodedata
from datetime import date
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from scripts.migrate import apply_migrations
from tests.integration.conftest import MIGRATIONS

TRIP_DEFAULTS: dict[str, Any] = {
    "destination_name": "Da Lat",
    "destination_country": "VN",
    "destination_lat": 11.94,
    "destination_lon": 108.44,
    "origin": "Ho Chi Minh City",
    "start_date": date(2026, 12, 20),
    "end_date": date(2026, 12, 23),
    "travelers": 4,
    "travel_styles": ["nature"],
    "budget_amount": 5_000_000,
    "budget_scope": "per_person",
    "local_currency": None,
    "language": "en",
    "status": "queued",
}


def insert_user(conn: psycopg.Connection, name: str) -> UUID:
    row = conn.execute("INSERT INTO users (name) VALUES (%s) RETURNING id", (name,)).fetchone()
    assert row is not None
    return row[0]


def insert_trip(conn: psycopg.Connection, user_id: UUID, **overrides: Any) -> UUID:
    values = {**TRIP_DEFAULTS, **overrides, "user_id": user_id}
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({key})s" for key in values)
    row = conn.execute(
        f"INSERT INTO trips ({columns}, expires_at) "
        f"VALUES ({placeholders}, now() + interval '30 days') RETURNING id",
        values,
    ).fetchone()
    assert row is not None
    return row[0]


def count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_migrate_is_idempotent(db_conn):
    assert apply_migrations(db_conn, MIGRATIONS) == []
    assert count(db_conn, "schema_migrations") == len(list(MIGRATIONS.glob("*.sql")))


def test_user_names_unique_ignoring_case_and_spaces(db_conn):
    insert_user(db_conn, "Đức")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_user(db_conn, "  đỨC ")


def test_user_name_key_folds_vietnamese_capitals(db_conn):
    insert_user(db_conn, unicodedata.normalize("NFC", "ĐỨC ANH"))
    row = db_conn.execute("SELECT name_key FROM users").fetchone()
    assert row == (unicodedata.normalize("NFC", "đức anh"),)


def test_user_name_rejects_blank_and_over_50_chars(db_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_user(db_conn, "   ")
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_user(db_conn, "x" * 51)


def test_trip_rejects_end_before_start(db_conn):
    user = insert_user(db_conn, "a")
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_trip(db_conn, user, end_date=date(2026, 12, 19))


def test_trip_allows_30_days_and_rejects_31(db_conn):
    user = insert_user(db_conn, "a")
    insert_trip(db_conn, user, start_date=date(2026, 12, 1), end_date=date(2026, 12, 30))
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_trip(db_conn, user, start_date=date(2026, 12, 1), end_date=date(2026, 12, 31))


def test_trip_local_currency_null_exactly_when_country_vn(db_conn):
    user = insert_user(db_conn, "a")
    insert_trip(db_conn, user, destination_country="TH", local_currency="THB")
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_trip(db_conn, user, destination_country="VN", local_currency="THB")
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_trip(db_conn, user, destination_country="TH", local_currency=None)


def test_trip_rejects_unknown_style_and_empty_styles(db_conn):
    user = insert_user(db_conn, "a")
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_trip(db_conn, user, travel_styles=["skydiving"])
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_trip(db_conn, user, travel_styles=[])


def test_trips_have_no_group_transport_or_conversation_column(db_conn):
    columns = {
        row[0]
        for row in db_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'trips'"
        ).fetchall()
    }
    assert not columns & {"group_type", "transport_modes", "conversation_id"}


def test_only_one_active_job_per_trip(db_conn):
    trip = insert_trip(db_conn, insert_user(db_conn, "a"))
    db_conn.execute(
        "INSERT INTO jobs (trip_id, kind, status) VALUES (%s, 'generate_plan', 'queued')", (trip,)
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_conn.execute(
            "INSERT INTO jobs (trip_id, kind, status) VALUES (%s, 'generate_plan', 'queued')",
            (trip,),
        )
    db_conn.execute("UPDATE jobs SET status = 'succeeded'")
    db_conn.execute(
        "INSERT INTO jobs (trip_id, kind, status) VALUES (%s, 'generate_plan', 'queued')", (trip,)
    )


def test_conversation_needs_only_a_user(db_conn):
    user = insert_user(db_conn, "a")
    db_conn.execute("INSERT INTO conversations (user_id) VALUES (%s)", (user,))
    db_conn.execute("INSERT INTO conversations (user_id) VALUES (%s)", (user,))
    assert count(db_conn, "conversations") == 2


def test_trip_plan_and_totals_are_set_together(db_conn):
    trip = insert_trip(db_conn, insert_user(db_conn, "a"))
    db_conn.execute(
        "UPDATE trips SET plan = %s, total_cost_vnd = 100, over_budget = false WHERE id = %s",
        (Jsonb({}), trip),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("UPDATE trips SET total_cost_vnd = NULL WHERE id = %s", (trip,))


def test_trip_starts_without_plan_at_revision_0(db_conn):
    trip = insert_trip(db_conn, insert_user(db_conn, "a"))
    row = db_conn.execute("SELECT plan, plan_revision FROM trips WHERE id = %s", (trip,)).fetchone()
    assert row == (None, 0)


def test_research_result_needs_exactly_one_owner(db_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("INSERT INTO research_results (kind, title) VALUES ('food', 'x')")


def test_deleting_trip_cascades_to_everything_under_it(db_conn):
    user = insert_user(db_conn, "a")
    trip = insert_trip(db_conn, user)
    db_conn.execute(
        "INSERT INTO jobs (trip_id, kind, status) VALUES (%s, 'generate_plan', 'succeeded')",
        (trip,),
    )
    db_conn.execute(
        "INSERT INTO research_results (trip_id, kind, title) VALUES (%s, 'food', 'x')", (trip,)
    )
    db_conn.execute(
        "INSERT INTO llm_calls (trip_id, purpose, model_id, outcome) VALUES (%s, 'generate', 'm', 'ok')",
        (trip,),
    )

    db_conn.execute("DELETE FROM trips WHERE id = %s", (trip,))

    for table in ("jobs", "research_results"):
        assert count(db_conn, table) == 0, table
    assert db_conn.execute("SELECT trip_id FROM llm_calls").fetchone() == (None,)


def test_llm_call_tracks_message_and_outlives_it(db_conn):
    user = insert_user(db_conn, "a")
    conversation = db_conn.execute(
        "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (user,)
    ).fetchone()[0]
    message = db_conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'hi') RETURNING id",
        (conversation,),
    ).fetchone()[0]
    db_conn.execute(
        "INSERT INTO llm_calls (conversation_id, message_id, purpose, model_id, outcome) "
        "VALUES (%s, %s, 'classify', 'm', 'ok')",
        (conversation, message),
    )

    db_conn.execute("DELETE FROM conversations WHERE id = %s", (conversation,))

    row = db_conn.execute("SELECT conversation_id, message_id, purpose FROM llm_calls").fetchone()
    assert row == (None, None, "classify")


def test_deleting_trip_keeps_conversations_and_messages(db_conn):
    user = insert_user(db_conn, "a")
    trip = insert_trip(db_conn, user)
    conversation = db_conn.execute(
        "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (user,)
    ).fetchone()[0]
    db_conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'hi')",
        (conversation,),
    )

    db_conn.execute("DELETE FROM trips WHERE id = %s", (trip,))

    assert count(db_conn, "conversations") == 1
    assert count(db_conn, "messages") == 1


def test_deleting_user_cascades_to_conversations_and_messages(db_conn):
    user = insert_user(db_conn, "a")
    conversation = db_conn.execute(
        "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (user,)
    ).fetchone()[0]
    db_conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'hi')",
        (conversation,),
    )

    db_conn.execute("DELETE FROM users WHERE id = %s", (user,))

    assert count(db_conn, "conversations") == 0
    assert count(db_conn, "messages") == 0
