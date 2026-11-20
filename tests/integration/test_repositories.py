from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.exceptions import Conflict, NotFound, PlanConflict
from db.repositories.conversations import (
    clear_draft,
    create_conversation,
    get_conversation,
    list_conversations,
    save_draft,
    touch_conversation,
)
from db.repositories.jobs import active_job, enqueue, finish, lease_next, requeue
from db.repositories.llm_calls import LlmCallRecord, count_today, log_call
from db.repositories.messages import (
    add_message,
    count_user_messages_today,
    find_open_questionnaire,
    get_message,
    recent_messages,
    update_open_metadata,
)
from db.repositories.quota import active_block, block, count_tavily_today
from db.repositories.research import (
    SourceInput,
    cache_get,
    cache_put,
    save_sources,
    sources_for_trip,
)
from db.repositories.trips import (
    TripRow,
    count_trips_today,
    create_trip,
    delete_trip,
    get_trip,
    list_trips,
    save_plan,
    set_status,
)
from db.repositories.users import UserRow, claim_user, get_user
from domain.trip_request import TripRequest

REQUEST: dict[str, Any] = {
    "destination": {"name": "Bangkok", "country_code": "TH", "lat": 13.75, "lon": 100.5},
    "origin": "Ho Chi Minh City",
    "start_date": "2026-12-20",
    "end_date": "2026-12-23",
    "travelers": 2,
    "travel_styles": ["food", "culture"],
    "budget_amount": "20000000",
    "budget_scope": "total",
    "language": "vi",
    "notes": None,
}
PLAN: dict[str, Any] = {"title": "Bangkok", "days": []}


@pytest.fixture
def user(db_conn) -> UserRow:
    return claim_user(db_conn, "Duy")


@pytest.fixture
def trip(db_conn, user) -> TripRow:
    return create_trip(db_conn, user.id, REQUEST, "THB", retention_days=30)


def test_claim_user_returns_same_row_for_same_name_any_case(db_conn):
    a = claim_user(db_conn, "Duy")
    b = claim_user(db_conn, " duy ")
    assert a.id == b.id and b.name == "Duy"
    assert b.last_seen_at is not None


def test_get_user_raises_not_found_for_unknown_id(db_conn, trip):
    with pytest.raises(NotFound):
        get_user(db_conn, trip.id)


def test_create_trip_maps_request_to_columns(db_conn, user, trip):
    assert (trip.destination_name, trip.destination_country, trip.local_currency) == (
        "Bangkok",
        "TH",
        "THB",
    )
    assert trip.travel_styles == ["food", "culture"] and trip.budget_amount == Decimal("20000000")
    assert (trip.status, trip.plan, trip.plan_revision) == ("queued", None, 0)
    assert trip.expires_at - trip.created_at == timedelta(days=30)
    assert count_trips_today(db_conn, user.id) == 1


def test_create_trip_accepts_trip_request_json_dump(db_conn, user):
    request = TripRequest.model_validate(REQUEST)
    row = create_trip(db_conn, user.id, request.model_dump(mode="json"), "THB", retention_days=30)
    assert row.budget_amount == request.budget_amount and row.start_date == request.start_date


def test_list_trips_newest_first_and_paged(db_conn, user, trip):
    newer = create_trip(db_conn, user.id, REQUEST, "THB", retention_days=30)
    assert [t.id for t in list_trips(db_conn, user.id, limit=10, offset=0)] == [newer.id, trip.id]
    assert [t.id for t in list_trips(db_conn, user.id, limit=1, offset=1)] == [trip.id]


def test_set_status_and_delete_trip(db_conn, trip):
    set_status(db_conn, trip.id, "failed", "quota_exhausted")
    assert get_trip(db_conn, trip.id).failure_reason == "quota_exhausted"
    delete_trip(db_conn, trip.id)
    with pytest.raises(NotFound):
        get_trip(db_conn, trip.id)
    with pytest.raises(NotFound):
        delete_trip(db_conn, trip.id)


def test_save_plan_overwrites_plan_and_bumps_revision(db_conn, trip):
    first = save_plan(db_conn, trip.id, 0, PLAN, Decimal("100"), False, "m")
    second = save_plan(db_conn, trip.id, 1, {**PLAN, "title": "v2"}, Decimal("90"), False, "m")
    assert (first.plan_revision, second.plan_revision) == (1, 2)
    saved = get_trip(db_conn, trip.id)
    assert saved.total_cost_vnd == Decimal("90") and saved.plan == {**PLAN, "title": "v2"}


def test_save_plan_with_stale_revision_raises_plan_conflict(db_conn, trip):
    save_plan(db_conn, trip.id, 0, PLAN, Decimal("100"), False, "m")
    with pytest.raises(PlanConflict):
        save_plan(db_conn, trip.id, 0, PLAN, Decimal("90"), False, "m")
    assert get_trip(db_conn, trip.id).total_cost_vnd == Decimal("100")


def test_save_plan_on_missing_trip_raises_not_found(db_conn, user):
    with pytest.raises(NotFound):
        save_plan(db_conn, user.id, 0, PLAN, Decimal("1"), False, "m")


def test_save_plan_with_request_writes_new_request_columns(db_conn, trip):
    new_request = {**REQUEST, "travelers": 4, "end_date": "2026-12-25", "notes": "vegan"}
    saved = save_plan(db_conn, trip.id, 0, PLAN, Decimal("1"), True, "m", request=new_request)
    assert (saved.travelers, saved.end_date.isoformat(), saved.notes) == (4, "2026-12-25", "vegan")


def test_enqueue_second_active_job_raises_conflict(db_conn, trip):
    job = enqueue(db_conn, trip.id, request=REQUEST)
    assert job.request == REQUEST and active_job(db_conn, trip.id) == job
    with pytest.raises(Conflict):
        enqueue(db_conn, trip.id)
    finish(db_conn, job.id, "succeeded")
    assert active_job(db_conn, trip.id) is None
    enqueue(db_conn, trip.id)


def test_two_connections_never_lease_the_same_job(db_pool, trip):
    with db_pool.connection() as setup:
        enqueue(setup, trip.id)
    with db_pool.connection() as c1, db_pool.connection() as c2:
        j1 = lease_next(c1, "w1", 60)
        j2 = lease_next(c2, "w2", 60)
    assert j1 is not None and j2 is None
    assert (j1.status, j1.attempts) == ("running", 1)


def test_expired_lease_is_leased_again(db_conn, trip):
    job = enqueue(db_conn, trip.id)
    assert lease_next(db_conn, "w1", 60) is not None
    assert lease_next(db_conn, "w2", 60) is None
    db_conn.execute(
        "UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s", (job.id,)
    )
    again = lease_next(db_conn, "w2", 60)
    assert again is not None and again.id == job.id and again.attempts == 2


def test_requeued_job_waits_for_run_after(db_conn, trip):
    job = enqueue(db_conn, trip.id)
    lease_next(db_conn, "w1", 60)
    requeue(db_conn, job.id, datetime.now(UTC) + timedelta(minutes=5), "timeout")
    assert lease_next(db_conn, "w1", 60) is None
    requeue(db_conn, job.id, datetime.now(UTC) - timedelta(seconds=1), "timeout")
    leased = lease_next(db_conn, "w1", 60)
    assert leased is not None and leased.last_error == "timeout"


def test_cache_get_ignores_expired_rows(db_conn):
    cache_put(db_conn, "fresh", "tavily", "q", {"a": 1}, timedelta(hours=1))
    cache_put(db_conn, "old", "tavily", "q", {"a": 2}, timedelta(seconds=-1))
    assert cache_get(db_conn, "fresh") == {"a": 1}
    assert cache_get(db_conn, "old") is None
    assert count_tavily_today(db_conn) == 2


def test_cache_put_replaces_row_with_same_key(db_conn):
    cache_put(db_conn, "k", "tavily", "q", {"a": 1}, timedelta(seconds=-1))
    cache_put(db_conn, "k", "tavily", "q", {"a": 2}, timedelta(hours=1))
    assert cache_get(db_conn, "k") == {"a": 2}


def test_save_sources_returns_ids_in_order(db_conn, trip):
    cache_put(db_conn, "k", "tavily", "q", {}, timedelta(hours=1))
    items = [SourceInput("A", "https://a", "a", "k"), SourceInput("B", None, "b")]
    rows = save_sources(db_conn, trip_id=trip.id, kind="food", items=items)
    assert [r.title for r in rows] == ["A", "B"] and rows[0].id < rows[1].id
    assert sources_for_trip(db_conn, trip.id) == rows


def test_list_conversations_newest_first(db_conn, user):
    older = create_conversation(db_conn, user.id, None)
    newer = create_conversation(db_conn, user.id, {"origin": "Hanoi"})
    assert [c.id for c in list_conversations(db_conn, user.id)] == [newer.id, older.id]
    touch_conversation(db_conn, older.id)
    assert [c.id for c in list_conversations(db_conn, user.id)] == [older.id, newer.id]


def test_save_draft_replaces_draft(db_conn, user):
    conversation = create_conversation(db_conn, user.id, None)
    save_draft(db_conn, conversation.id, {"travelers": 3})
    assert get_conversation(db_conn, conversation.id).request_draft == {"travelers": 3}


def test_clear_draft_sets_request_draft_to_null(db_conn, user):
    conversation = create_conversation(db_conn, user.id, {"travelers": 3})
    clear_draft(db_conn, conversation.id)
    assert get_conversation(db_conn, conversation.id).request_draft is None


def test_get_unknown_message_raises_not_found(db_conn, user):
    conversation = create_conversation(db_conn, user.id, None)
    message = add_message(db_conn, conversation.id, "assistant", "Hi", "advice")
    assert get_message(db_conn, message.id) == message
    with pytest.raises(NotFound):
        get_message(db_conn, conversation.id)


def test_update_open_metadata_changes_only_a_matching_row(db_conn, user):
    conversation = create_conversation(db_conn, user.id, None)
    form = add_message(
        db_conn,
        conversation.id,
        "assistant",
        "",
        "create_trip",
        {"status": "open", "draft": {"length_days": 3}, "trip_id": None},
    )
    created = {"status": "created", "draft": {"length_days": 3}, "trip_id": "x"}
    updated = update_open_metadata(db_conn, form.id, {"status": "open"}, created)
    assert updated is not None
    assert updated.metadata == created
    canceled = {"status": "canceled", "draft": {}, "trip_id": None}
    assert update_open_metadata(db_conn, form.id, {"status": "open"}, canceled) is None
    assert get_message(db_conn, form.id).metadata == created


def test_find_open_questionnaire_returns_the_open_card_only(db_conn, user):
    conversation = create_conversation(db_conn, user.id, None)
    card = {"kind": "questionnaire", "status": "open", "step": 0, "answers": {}, "choices": {}}
    assert find_open_questionnaire(db_conn, conversation.id) is None
    done = add_message(
        db_conn, conversation.id, "assistant", "", "discover", {**card, "status": "done"}
    )
    open_card = add_message(db_conn, conversation.id, "assistant", "", "discover", card)
    found = find_open_questionnaire(db_conn, conversation.id)
    assert found is not None
    assert found.id == open_card.id != done.id
    update_open_metadata(db_conn, open_card.id, {"status": "open"}, {**card, "status": "done"})
    assert find_open_questionnaire(db_conn, conversation.id) is None


def test_recent_messages_returns_last_n_oldest_first(db_conn, user):
    conversation = create_conversation(db_conn, user.id, None)
    with db_conn.transaction():
        for text in ("one", "two", "three"):
            add_message(db_conn, conversation.id, "user", text)
    cards = {"kind": "suggestions", "cards": [{"name": "Hue"}]}
    add_message(db_conn, conversation.id, "assistant", "cards", "discover", cards)
    recent = recent_messages(db_conn, conversation.id, limit=3)
    assert [m.content for m in recent] == ["two", "three", "cards"]
    assert recent[-1].metadata == cards
    assert count_user_messages_today(db_conn, user.id) == 3


def test_count_today_filters_by_purpose(db_conn, trip):
    log_call(db_conn, LlmCallRecord("generate", "m", "ok", trip_id=trip.id, input_tokens=10))
    log_call(db_conn, LlmCallRecord("classify", "m", "rate_limited", error="429"))
    assert count_today(db_conn) == 2
    assert count_today(db_conn, ["generate", "repair"]) == 1


def test_active_block_ignores_expired_block(db_conn):
    until = datetime.now(UTC) + timedelta(hours=1)
    block(db_conn, "openrouter", until, "daily cap")
    assert active_block(db_conn, "openrouter") == until
    block(db_conn, "openrouter", datetime.now(UTC) - timedelta(seconds=1), "daily cap")
    assert active_block(db_conn, "openrouter") is None
    assert active_block(db_conn, "tavily") is None
