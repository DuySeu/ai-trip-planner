from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from db.repositories.conversations import create_conversation
from db.repositories.jobs import enqueue
from db.repositories.messages import add_message
from db.repositories.research import SourceInput, cache_put, save_sources
from db.repositories.trips import create_trip, get_trip
from db.repositories.users import claim_user
from service.worker.cleanup import CleanupCounts, run_cleanup

NOW = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)
INACTIVE_DAYS = 90
REQUEST: dict[str, Any] = {
    "destination": {"name": "Bangkok", "country_code": "TH", "lat": 13.75, "lon": 100.5},
    "origin": "Ho Chi Minh City",
    "start_date": "2026-12-20",
    "end_date": "2026-12-23",
    "travelers": 2,
    "travel_styles": ["food"],
    "budget_amount": "20000000",
    "budget_scope": "total",
    "language": "en",
    "notes": None,
}


# Move a trip's expiry to a fixed time
def set_expiry(conn, trip_id, expires_at: datetime) -> None:
    conn.execute("UPDATE trips SET expires_at = %s WHERE id = %s", (expires_at, trip_id))


# Set when a user was last seen
def set_last_seen(conn, user_id, last_seen_at: datetime) -> None:
    conn.execute("UPDATE users SET last_seen_at = %s WHERE id = %s", (last_seen_at, user_id))


def count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


@pytest.fixture
def user(db_conn):
    row = claim_user(db_conn, "Duy")
    set_last_seen(db_conn, row.id, NOW)
    return row


def test_expired_trip_and_its_rows_are_deleted(db_conn, user):
    trip = create_trip(db_conn, user.id, REQUEST, "THB", retention_days=30)
    enqueue(db_conn, trip.id)
    save_sources(
        db_conn, trip_id=trip.id, kind="food", items=[SourceInput("Pad thai", None, "snippet")]
    )
    set_expiry(db_conn, trip.id, NOW - timedelta(seconds=1))

    counts = run_cleanup(db_conn, NOW, INACTIVE_DAYS)

    assert counts == CleanupCounts(trips=1, conversations=0, users=0, cache_rows=0)
    assert [count(db_conn, t) for t in ("trips", "jobs", "research_results")] == [0, 0, 0]
    assert count(db_conn, "users") == 1


def test_trip_touched_yesterday_is_kept(db_conn, user):
    trip = create_trip(db_conn, user.id, REQUEST, "THB", retention_days=30)
    set_expiry(db_conn, trip.id, NOW + timedelta(days=29))

    counts = run_cleanup(db_conn, NOW, INACTIVE_DAYS)

    assert counts.trips == 0
    assert get_trip(db_conn, trip.id).id == trip.id


def test_inactive_user_without_trips_is_deleted_and_name_freed(db_conn, user):
    conversation = create_conversation(db_conn, user.id, None)
    add_message(db_conn, conversation.id, "user", "hello")
    set_last_seen(db_conn, user.id, NOW - timedelta(days=INACTIVE_DAYS, seconds=1))

    counts = run_cleanup(db_conn, NOW, INACTIVE_DAYS)

    assert (counts.users, counts.conversations) == (1, 1)
    assert [count(db_conn, t) for t in ("users", "conversations", "messages")] == [0, 0, 0]
    assert claim_user(db_conn, "duy").id != user.id


def test_user_seen_within_the_window_is_kept(db_conn, user):
    set_last_seen(db_conn, user.id, NOW - timedelta(days=INACTIVE_DAYS - 1))

    assert run_cleanup(db_conn, NOW, INACTIVE_DAYS).users == 0
    assert count(db_conn, "users") == 1


def test_inactive_user_with_a_trip_is_kept(db_conn, user):
    create_trip(db_conn, user.id, REQUEST, "THB", retention_days=30)
    set_last_seen(db_conn, user.id, NOW - timedelta(days=INACTIVE_DAYS + 10))

    counts = run_cleanup(db_conn, NOW, INACTIVE_DAYS)

    assert counts.users == 0 and count(db_conn, "users") == 1


def test_user_whose_only_trip_just_expired_is_deleted_in_the_same_run_when_inactive(db_conn, user):
    trip = create_trip(db_conn, user.id, REQUEST, "THB", retention_days=30)
    set_expiry(db_conn, trip.id, NOW - timedelta(days=1))
    set_last_seen(db_conn, user.id, NOW - timedelta(days=INACTIVE_DAYS + 1))

    counts = run_cleanup(db_conn, NOW, INACTIVE_DAYS)

    assert (counts.trips, counts.users) == (1, 1)


def test_expired_cache_rows_are_deleted(db_conn):
    cache_put(db_conn, "old", "tavily", "q", {"a": 1}, timedelta(hours=1))
    cache_put(db_conn, "fresh", "tavily", "q", {"a": 2}, timedelta(days=30))

    counts = run_cleanup(db_conn, datetime.now(UTC) + timedelta(days=1), INACTIVE_DAYS)

    assert counts.cache_rows == 1
    assert [r[0] for r in db_conn.execute("SELECT key FROM search_cache")] == ["fresh"]
