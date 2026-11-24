from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import Connection

from db.repositories import stats
from db.repositories.conversations import create_conversation
from db.repositories.jobs import enqueue, finish
from db.repositories.llm_calls import LlmCallRecord, log_call
from db.repositories.messages import add_message
from db.repositories.quota import block
from db.repositories.stats import Count, Destination
from db.repositories.trips import create_trip, save_plan, set_status
from db.repositories.users import claim_user
from domain.trip_request import today_in_vietnam
from tests.fixtures.builders import BANGKOK_FIELDS, DALAT_FIELDS

VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


# Move one row of a table to a fixed creation time
def set_created(conn: Connection[Any], table: str, row_id: Any, at: datetime) -> None:
    conn.execute(f"UPDATE {table} SET created_at = %s WHERE id = %s", (at, row_id))


# A trip for a new user, from form fields with overrides
def make_trip(
    conn: Connection[Any], user_id: UUID, fields: dict[str, Any], currency: str | None
) -> UUID:
    return create_trip(conn, user_id, fields, currency).id


def test_health_on_empty_database(db_conn):
    h = stats.health(db_conn, 800, 950)

    assert (h.llm_today.calls, h.llm_today.ceiling_new_trips, h.llm_today.ceiling_chat) == (
        0,
        800,
        950,
    )
    assert (h.llm_last_hour.p50_latency_ms, h.plans_last_day.p95_s, h.jobs.oldest_queued_s) == (
        None,
        None,
        None,
    )
    assert h.blocks == [] and h.plans_last_day.last_failure is None


def test_health_counts_llm_calls_with_null_tokens(db_conn):
    log_call(
        db_conn,
        LlmCallRecord("classify", "m/a", "ok", input_tokens=100, output_tokens=20, latency_ms=1000),
    )
    log_call(db_conn, LlmCallRecord("classify", "m/a", "rate_limited"))
    log_call(db_conn, LlmCallRecord("answer", "m/b", "ok", latency_ms=3000))
    log_call(db_conn, LlmCallRecord("answer", "m/b", "ok", input_tokens=7))
    db_conn.execute(
        "UPDATE llm_calls SET created_at = now() - interval '2 days' WHERE input_tokens = 7"
    )

    h = stats.health(db_conn, 800, 950)

    assert (h.llm_today.calls, h.llm_today.input_tokens, h.llm_today.output_tokens) == (3, 100, 20)
    assert (h.llm_last_hour.calls, h.llm_last_hour.errors) == (3, 1)
    assert h.llm_last_hour.outcomes == [Count("ok", 2), Count("rate_limited", 1)]
    assert h.llm_last_hour.p50_latency_ms == 2000.0


def test_health_job_queue_and_last_failure(db_conn):
    user = claim_user(db_conn, "Linh")
    queued = enqueue(db_conn, make_trip(db_conn, user.id, DALAT_FIELDS, None))
    db_conn.execute(
        "UPDATE jobs SET created_at = now() - interval '10 minutes' WHERE id = %s", (queued.id,)
    )
    running = enqueue(db_conn, make_trip(db_conn, user.id, DALAT_FIELDS, None))
    db_conn.execute("UPDATE jobs SET status = 'running' WHERE id = %s", (running.id,))

    failed_trip = make_trip(db_conn, user.id, BANGKOK_FIELDS, "THB")
    failed = enqueue(db_conn, failed_trip)
    finish(db_conn, failed.id, "failed", "notes: secret")
    set_status(db_conn, failed_trip, "failed", "quota_exhausted")
    db_conn.execute(
        "UPDATE jobs SET finished_at = now() - interval '1 hour' WHERE id = %s", (failed.id,)
    )

    done = enqueue(db_conn, make_trip(db_conn, user.id, DALAT_FIELDS, None))
    finish(db_conn, done.id, "succeeded")
    db_conn.execute(
        "UPDATE jobs SET created_at = finished_at - interval '60 seconds' WHERE id = %s", (done.id,)
    )

    h = stats.health(db_conn, 800, 950)

    assert (h.jobs.queued, h.jobs.running) == (1, 1)
    assert h.jobs.oldest_queued_s is not None and 590 <= h.jobs.oldest_queued_s <= 610
    assert h.plans_last_day.failed == 1
    assert h.plans_last_day.last_failure is not None
    assert h.plans_last_day.last_failure.reason == "quota_exhausted"
    assert (h.plans_last_day.succeeded, h.plans_last_day.p50_s) == (1, 60.0)


def test_health_lists_only_active_blocks(db_conn):
    now = datetime.now(UTC)
    block(db_conn, "openrouter", now + timedelta(hours=1), "cap")
    block(db_conn, "tavily", now - timedelta(hours=1), "cap")

    assert [b.service for b in stats.health(db_conn, 800, 950).blocks] == ["openrouter"]


def test_usage_on_empty_database(db_conn):
    u = stats.usage(db_conn, 7)

    assert len(u.daily) == 7 and all((d.trips, d.messages) == (0, 0) for d in u.daily)
    assert u.daily[-1].day == today_in_vietnam(datetime.now(UTC))
    assert u.trips.median_budget_per_person_vnd is None and u.destinations == []
    assert (u.users.total, u.trips.created, u.messages) == (0, 0, 0)


def test_daily_series_uses_vietnam_days(db_conn):
    user = claim_user(db_conn, "Linh")
    midnight = datetime.now(VIETNAM).replace(hour=0, minute=0, second=0, microsecond=0)
    late = make_trip(db_conn, user.id, DALAT_FIELDS, None)
    early = make_trip(db_conn, user.id, DALAT_FIELDS, None)
    set_created(db_conn, "trips", late, midnight - timedelta(minutes=1))
    set_created(db_conn, "trips", early, midnight + timedelta(minutes=1))

    u = stats.usage(db_conn, 7)

    assert [d.trips for d in u.daily[-2:]] == [1, 1]


def test_usage_counts_trips_users_and_chat(db_conn):
    now = datetime.now(UTC)
    linh = claim_user(db_conn, "Linh")
    minh = claim_user(db_conn, "Minh")
    set_created(db_conn, "users", minh.id, now - timedelta(days=100))
    db_conn.execute(
        "UPDATE users SET last_seen_at = %s WHERE id = %s", (now - timedelta(days=1), minh.id)
    )

    dalat = make_trip(
        db_conn,
        linh.id,
        {**DALAT_FIELDS, "budget_amount": "8000000", "budget_scope": "total", "travelers": 2},
        None,
    )
    save_plan(db_conn, dalat, 0, {"title": "x"}, 1000, False, "m/a")
    set_status(db_conn, dalat, "ready")
    bangkok = make_trip(
        db_conn, minh.id, {**BANGKOK_FIELDS, "budget_amount": "10000000", "travelers": 1}, "THB"
    )
    set_status(db_conn, bangkok, "failed", "generation_failed")
    old = make_trip(db_conn, minh.id, DALAT_FIELDS, None)
    set_created(db_conn, "trips", old, now - timedelta(days=40))

    conversation = create_conversation(db_conn, linh.id, None)
    for text in ("a", "b", "c"):
        add_message(db_conn, conversation.id, "user", text)
    add_message(db_conn, conversation.id, "assistant", "x", "advice")
    add_message(db_conn, conversation.id, "assistant", "y", "advice")
    add_message(db_conn, conversation.id, "assistant", "", "create_trip", {"status": "open"})
    add_message(db_conn, conversation.id, "assistant", "", "create_trip", {"status": "created"})

    u = stats.usage(db_conn, 30)

    assert (u.users.total, u.users.new, u.users.active) == (2, 1, 2)
    assert (u.trips.created, u.trips.domestic, u.trips.abroad) == (2, 1, 1)
    assert u.trips.by_status == [Count("failed", 1), Count("ready", 1)]
    assert u.trips.median_budget_per_person_vnd == 7_000_000.0
    assert (u.trips.with_plan, u.trips.over_budget) == (1, 0)
    assert u.destinations == [Destination("Bangkok", "TH", 1), Destination("Đà Lạt", "VN", 1)]
    assert u.styles[0] == Count("food", 2)
    assert (u.conversations, u.messages) == (1, 3)
    assert u.intents == [Count("advice", 2), Count("create_trip", 2)]
    assert u.trip_forms == [Count("created", 1), Count("open", 1)]
    assert sum(d.trips for d in u.daily) == 2
