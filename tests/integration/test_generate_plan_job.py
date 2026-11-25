from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from psycopg.rows import class_row

from core.constants import ModelId
from core.exceptions import QuotaExhausted, ResearchFailed
from core.settings import load_settings
from db.repositories.jobs import JobRow, add_llm_calls, enqueue, lease_next
from db.repositories.research import sources_for_trip
from db.repositories.trips import TripRow, create_trip, get_trip, save_plan, set_status
from db.repositories.users import claim_user
from domain.plan import Plan
from models.llm_factory import ProviderCallError
from models.model_router import ModelRouter
from research.research_service import ResearchDeps
from service.tavily.search import SearchHit, WebSearch
from service.worker import worker
from service.worker.generate_plan import JobDeps, run_generate_plan, save_new_sources
from tests.fakes import FakeProvider, FakeSearch, FakeSink
from tests.fixtures.builders import bangkok_plan, bangkok_request
from tests.unit.test_plan_generator import answer

MODEL = ModelId.LING_3_2_FLASH
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
ENV = {
    "DB_USER": "u",
    "DB_PASSWORD": "p",
    "DB_NAME": "n",
    "OPENROUTER_API_KEY": "k",
    "TAVILY_API_KEY": "k",
    "PLANNER_MODELS": MODEL,
    "CHAT_MODELS": MODEL,
    "CLASSIFIER_MODELS": MODEL,
    "DAILY_LLM_CEILING_NEW_TRIPS": "10",
    "DAILY_LLM_CEILING_CHAT": "20",
    "DAILY_TAVILY_CEILING": "10",
}
HITS = [
    SearchHit("Grand Palace", "https://example.com/a", "Grand Palace 500 THB"),
    SearchHit("Pad thai", "https://example.com/b", "Pad thai 60 THB"),
]
UNAVAILABLE = ProviderCallError("provider_error", "ConnectError: down")


# Everything one test needs to run a job and look at the result
@dataclass
class Rig:
    deps: JobDeps
    provider: FakeProvider
    sink: FakeSink


# Job deps with a scripted LLM, a fake search and the real source saving against the test database
def make_rig(
    pool: Any,
    script: Sequence[str | Exception],
    search: WebSearch | None = None,
    **settings: str,
) -> Rig:
    provider = FakeProvider(script)
    sink = FakeSink()
    router = ModelRouter(
        llm=provider,
        models={"generate": [MODEL], "repair": [MODEL]},
        sink=sink,
        reset_hour_utc=0,
        now=lambda: NOW,
    )
    research = ResearchDeps(
        search=search or FakeSearch(default=HITS),
        weather=lambda lat, lon, start, end, today: {},
        rate=lambda currency, today: (Decimal("700"), date(2026, 11, 17)),
        save_sources=lambda trip_id, kind, hits: save_new_sources(pool, trip_id, kind, hits),
    )
    deps = JobDeps(
        settings=load_settings({**ENV, **settings}),
        pool=pool,
        router=router,
        research=research,
        now=lambda: NOW,
    )
    return Rig(deps, provider, sink)


# A queued Bangkok trip with no plan
@pytest.fixture
def queued_trip(db_conn: Any) -> TripRow:
    user = claim_user(db_conn, "Duy")
    request = bangkok_request().model_dump(mode="json")
    return create_trip(db_conn, user.id, request, "THB")


# A ready trip holding the Bangkok plan at revision 1
@pytest.fixture
def ready_trip(queued_trip: TripRow, db_conn: Any) -> TripRow:
    plan = bangkok_plan().model_dump(mode="json")
    save_plan(db_conn, queued_trip.id, 0, plan, Decimal("1000000"), False, "old/model")
    set_status(db_conn, queued_trip.id, "ready")
    return get_trip(db_conn, queued_trip.id)


# Queue a job for the trip and lease it, as the worker would
def lease(conn: Any, trip: TripRow, request: dict[str, Any] | None = None) -> JobRow:
    enqueue(conn, trip.id, request=request)
    job = lease_next(conn, "w1", 600)
    assert job is not None
    return job


# Make the trip's queued job due now, as when its backoff has passed, and lease it again
def lease_again(conn: Any) -> JobRow:
    conn.execute("UPDATE jobs SET run_after = now() WHERE status = 'queued'")
    job = lease_next(conn, "w1", 600)
    assert job is not None
    return job


# The job row as stored now
def stored_job(conn: Any, job: JobRow) -> JobRow:
    with conn.cursor(row_factory=class_row(JobRow)) as cur:
        row = cur.execute("SELECT * FROM jobs WHERE id = %s", (job.id,)).fetchone()
    assert row is not None
    return row


def test_job_turns_queued_trip_into_ready_with_plan_at_revision_1(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, [answer()])
    job = lease(db_conn, queued_trip)

    run_generate_plan(job, rig.deps)

    trip = get_trip(db_conn, queued_trip.id)
    assert (trip.status, trip.plan_revision, trip.failure_reason) == ("ready", 1, None)
    assert trip.model_id == MODEL and trip.over_budget is False
    plan = Plan.model_validate(trip.plan)
    assert plan.currencies.local == "THB" and plan.currencies.local_to_home_rate == Decimal("700")
    done = stored_job(db_conn, job)
    assert (done.status, done.llm_calls_used, done.finished_at is not None) == (
        "succeeded",
        1,
        True,
    )
    assert len(sources_for_trip(db_conn, trip.id)) == 10


def test_plan_source_ids_all_resolve_to_saved_sources(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, [answer()])
    run_generate_plan(lease(db_conn, queued_trip), rig.deps)

    trip = get_trip(db_conn, queued_trip.id)
    plan = Plan.model_validate(trip.plan)
    cited = {
        e.source_id
        for e in (
            *[i for d in plan.days for i in d.items],
            *plan.transport_options,
            *plan.accommodation,
        )
        if e.source_id is not None
    }
    assert cited and cited <= {s.id for s in sources_for_trip(db_conn, trip.id)}


@pytest.mark.parametrize("blocker", ["openrouter", "search"])
def test_quota_exhausted_fails_trip_without_retry(db_pool, db_conn, queued_trip, blocker):
    def search_over_quota(query: str, task: str) -> list[SearchHit]:
        raise QuotaExhausted(NOW + timedelta(days=1))

    rig = make_rig(db_pool, [answer()], search=search_over_quota if blocker == "search" else None)
    if blocker == "openrouter":
        rig.sink.block("openrouter", NOW + timedelta(hours=5), "daily cap")
    job = lease(db_conn, queued_trip)

    run_generate_plan(job, rig.deps)

    trip = get_trip(db_conn, queued_trip.id)
    assert (trip.status, trip.failure_reason, trip.plan) == ("failed", "quota_exhausted", None)
    done = stored_job(db_conn, job)
    assert done.status == "failed" and done.attempts == 1 and "quota exhausted" in done.last_error
    assert rig.provider.calls == []


def test_llm_budget_exceeded_fails_trip_without_retry(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, [answer()], LLM_CALLS_PER_JOB="2")
    enqueue(db_conn, queued_trip.id)
    job = lease_next(db_conn, "w1", 600)
    assert job is not None
    add_llm_calls(db_conn, job.id, 2)
    job = stored_job(db_conn, job)

    run_generate_plan(job, rig.deps)

    trip = get_trip(db_conn, queued_trip.id)
    assert (trip.status, trip.failure_reason) == ("failed", "llm_budget_exceeded")
    done = stored_job(db_conn, job)
    assert (done.status, done.llm_calls_used) == ("failed", 2)
    assert rig.provider.calls == []


def no_search(query: str, task: str) -> list[SearchHit]:
    raise ResearchFailed("tavily is down")


@pytest.mark.parametrize(
    ("script", "search"),
    [
        pytest.param([], no_search, id="research_failed"),
        pytest.param(["not json"] * 6, None, id="invalid_llm_output"),
        pytest.param([UNAVAILABLE] * 3, None, id="llm_unavailable"),
    ],
)
def test_transient_failure_requeues_with_backoff_then_fails_after_max_attempts(
    db_pool, db_conn, queued_trip, script, search
):
    rig = make_rig(db_pool, script, search=search, LLM_CALLS_PER_JOB="20")
    job = lease(db_conn, queued_trip)

    # Attempt 1 of 3: back in the queue 30 s later, the trip waits as queued
    run_generate_plan(job, rig.deps)
    waiting = stored_job(db_conn, job)
    assert (waiting.status, waiting.run_after) == ("queued", NOW + timedelta(seconds=30))
    assert waiting.leased_until is None and waiting.last_error
    assert get_trip(db_conn, queued_trip.id).status == "queued"

    # Attempt 2: 60 s later
    run_generate_plan(lease_again(db_conn), rig.deps)
    waiting = stored_job(db_conn, job)
    assert (waiting.status, waiting.attempts, waiting.run_after) == (
        "queued",
        2,
        NOW + timedelta(seconds=60),
    )

    # Attempt 3 is the last: the job and the trip fail
    run_generate_plan(lease_again(db_conn), rig.deps)
    done = stored_job(db_conn, job)
    assert (done.status, done.attempts, done.finished_at is not None) == ("failed", 3, True)
    trip = get_trip(db_conn, queued_trip.id)
    assert (trip.status, trip.failure_reason, trip.plan) == ("failed", "generation_failed", None)


def test_llm_calls_used_accumulates_across_attempts_and_stops_at_cap(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, [UNAVAILABLE] * 4, LLM_CALLS_PER_JOB="3")
    job = lease(db_conn, queued_trip)
    db_conn.execute("UPDATE jobs SET max_attempts = 5 WHERE id = %s", (job.id,))

    run_generate_plan(job, rig.deps)
    run_generate_plan(lease_again(db_conn), rig.deps)
    run_generate_plan(lease_again(db_conn), rig.deps)
    assert stored_job(db_conn, job).llm_calls_used == 3

    # The fourth attempt may not call the model: the cap spans attempts
    run_generate_plan(lease_again(db_conn), rig.deps)
    done = stored_job(db_conn, job)
    assert (done.status, done.llm_calls_used, len(rig.provider.calls)) == ("failed", 3, 3)
    trip = get_trip(db_conn, queued_trip.id)
    assert (trip.status, trip.failure_reason) == ("failed", "llm_budget_exceeded")


def test_job_leased_more_than_max_attempts_is_failed_without_running(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, [answer()])
    job = lease(db_conn, queued_trip)
    # Two worker deaths: the lease expired and the job was leased a fourth time
    db_conn.execute("UPDATE jobs SET attempts = 4 WHERE id = %s", (job.id,))

    run_generate_plan(stored_job(db_conn, job), rig.deps)

    assert stored_job(db_conn, job).status == "failed"
    trip = get_trip(db_conn, queued_trip.id)
    assert (trip.status, trip.failure_reason) == ("failed", "generation_failed")
    assert rig.provider.calls == []


def test_retried_job_adds_no_duplicate_sources_and_plan_sources_resolve(
    db_pool, db_conn, queued_trip
):
    rig = make_rig(db_pool, [UNAVAILABLE, answer()])
    job = lease(db_conn, queued_trip)

    run_generate_plan(job, rig.deps)
    first = {(s.kind, s.url): s.id for s in sources_for_trip(db_conn, queued_trip.id)}
    run_generate_plan(lease_again(db_conn), rig.deps)

    rows = sources_for_trip(db_conn, queued_trip.id)
    assert len(rows) == len(first) == 10
    assert {(s.kind, s.url): s.id for s in rows} == first
    trip = get_trip(db_conn, queued_trip.id)
    assert trip.status == "ready"
    plan = Plan.model_validate(trip.plan)
    cited = {i.source_id for d in plan.days for i in d.items if i.source_id is not None}
    assert cited and cited <= {s.id for s in rows}


def test_save_new_sources_returns_one_row_per_hit_and_saves_only_new_ones(
    db_pool, db_conn, queued_trip
):
    first = save_new_sources(db_pool, queued_trip.id, "food", HITS)
    extra = SearchHit("Som tam", "https://example.com/c", "Som tam 40 THB")
    second = save_new_sources(db_pool, queued_trip.id, "food", [HITS[1], extra, HITS[1]])

    assert [r.url for r in second] == [HITS[1].url, extra.url, HITS[1].url]
    assert second[0].id == first[1].id == second[2].id
    assert len(sources_for_trip(db_conn, queued_trip.id)) == 3


def test_same_url_under_another_kind_is_saved_separately(db_pool, db_conn, queued_trip):
    save_new_sources(db_pool, queued_trip.id, "food", HITS)
    save_new_sources(db_pool, queued_trip.id, "activities", HITS)
    assert len(sources_for_trip(db_conn, queued_trip.id)) == 4


def new_request() -> dict[str, Any]:
    return bangkok_request(travelers=3, budget_amount="25000000", notes="more food").model_dump(
        mode="json"
    )


def test_replan_uses_new_request_and_previous_plan_and_saves_both_at_revision_2(
    db_pool, db_conn, ready_trip
):
    rig = make_rig(db_pool, [answer()])
    job = lease(db_conn, ready_trip, request=new_request())

    run_generate_plan(job, rig.deps)

    content = rig.provider.calls[0][0][0]["content"]
    assert "travelers: 3" in content and "more food" in content
    assert "<previous_plan>" in content and bangkok_plan().title in content
    trip = get_trip(db_conn, ready_trip.id)
    assert (trip.status, trip.plan_revision, trip.travelers, trip.notes) == (
        "ready",
        2,
        3,
        "more food",
    )
    assert trip.model_id == MODEL
    assert stored_job(db_conn, job).status == "succeeded"


@pytest.mark.parametrize(
    ("script", "reason"),
    [([UNAVAILABLE] * 3, "generation_failed"), ([], "quota_exhausted")],
)
def test_failed_replan_keeps_trip_ready_with_old_plan_and_request(
    db_pool, db_conn, ready_trip, script, reason
):
    rig = make_rig(db_pool, script)
    if reason == "quota_exhausted":
        rig.sink.block("openrouter", NOW + timedelta(hours=5), "daily cap")
    job = lease(db_conn, ready_trip, request=new_request())
    db_conn.execute("UPDATE jobs SET max_attempts = 1 WHERE id = %s", (job.id,))

    run_generate_plan(stored_job(db_conn, job), rig.deps)

    trip = get_trip(db_conn, ready_trip.id)
    assert (trip.status, trip.failure_reason) == ("ready", reason)
    assert trip.plan == ready_trip.plan and trip.plan_revision == 1
    assert (trip.travelers, trip.notes) == (ready_trip.travelers, ready_trip.notes)
    assert stored_job(db_conn, job).status == "failed"


def test_plan_conflict_at_save_fails_job_and_leaves_trip_ready_without_retry(
    db_pool, db_conn, ready_trip, monkeypatch, caplog
):
    rig = make_rig(db_pool, [answer()])
    job = lease(db_conn, ready_trip, request=new_request())

    # A chat edit lands between reading the revision and saving
    real_save = save_plan

    def save_after_edit(conn: Any, trip_id: Any, base_revision: int, *args: Any, **kw: Any) -> Any:
        return real_save(conn, trip_id, base_revision + 1, *args, **kw)

    monkeypatch.setattr("service.worker.generate_plan.trips.save_plan", save_after_edit)
    with caplog.at_level(logging.WARNING):
        run_generate_plan(job, rig.deps)

    trip = get_trip(db_conn, ready_trip.id)
    assert (trip.status, trip.failure_reason, trip.plan_revision) == ("ready", "plan_conflict", 1)
    assert trip.plan == ready_trip.plan and trip.travelers == ready_trip.travelers
    done = stored_job(db_conn, job)
    assert done.status == "failed" and done.attempts == 1
    assert "plan changed" in caplog.text


def test_calls_made_by_a_failed_attempt_are_still_counted(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, ["not json", "not json"], LLM_CALLS_PER_JOB="20")
    job = lease(db_conn, queued_trip)
    run_generate_plan(job, rig.deps)
    assert stored_job(db_conn, job).llm_calls_used == 2


# Run the worker in a thread until the condition holds, then stop it and wait for it to end
def run_worker_until(rig: Rig, condition: Callable[[], bool], **kwargs: Any) -> None:
    stop = threading.Event()
    thread = threading.Thread(
        target=worker.run_worker, args=(rig.deps, "w-test", 0.05, stop), kwargs=kwargs
    )
    thread.start()
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    while not condition() and datetime.now(UTC) < deadline:
        stop.wait(0.05)
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_worker_runs_a_queued_job_and_stops_cleanly_when_stop_event_set(
    db_pool, db_conn, queued_trip
):
    rig = make_rig(db_pool, [answer()])
    enqueue(db_conn, queued_trip.id)

    run_worker_until(rig, lambda: get_trip(db_conn, queued_trip.id).status == "ready")

    assert get_trip(db_conn, queued_trip.id).plan_revision == 1


def test_worker_with_no_jobs_stops_cleanly_when_stop_event_set(db_pool, db_conn):
    rig = make_rig(db_pool, [])
    run_worker_until(rig, lambda: True)


def test_worker_finishes_the_running_job_before_stopping(db_pool, db_conn, queued_trip):
    rig = make_rig(db_pool, [answer()])
    enqueue(db_conn, queued_trip.id)
    stop = threading.Event()
    real_generate = rig.deps.router.invoke_model

    # Ask the worker to stop while the model is answering
    def stop_midway(*args: Any, **kwargs: Any) -> Any:
        stop.set()
        return real_generate(*args, **kwargs)

    rig.deps.router.invoke_model = stop_midway  # type: ignore[method-assign]
    thread = threading.Thread(target=worker.run_worker, args=(rig.deps, "w-test", 0.05, stop))
    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert get_trip(db_conn, queued_trip.id).status == "ready"


def test_worker_runs_cleanup_at_start_and_keeps_old_trips(db_pool, db_conn, queued_trip, caplog):
    db_conn.execute("UPDATE trips SET updated_at = %s", (NOW - timedelta(days=365),))
    rig = make_rig(db_pool, [])

    with caplog.at_level(logging.INFO):
        run_worker_until(rig, lambda: "cleanup deleted" in caplog.text)

    assert db_conn.execute("SELECT count(*) FROM trips").fetchone()[0] == 1


def test_worker_repeats_cleanup_when_the_interval_has_passed(db_pool, db_conn, caplog):
    rig = make_rig(db_pool, [])
    with caplog.at_level(logging.INFO):
        run_worker_until(
            rig,
            lambda: caplog.text.count("cleanup deleted") >= 2,
            cleanup_every=timedelta(0),
        )
    assert caplog.text.count("cleanup deleted") >= 2


def test_worker_logs_a_heartbeat(db_pool, db_conn, caplog, monkeypatch):
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.0)
    rig = make_rig(db_pool, [])
    with caplog.at_level(logging.INFO):
        run_worker_until(rig, lambda: "heartbeat" in caplog.text)
    assert "w-test heartbeat" in caplog.text


def test_sigterm_sets_the_stop_event():
    stop = threading.Event()
    previous = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    try:
        worker.stop_on_signal(stop)
        signal.raise_signal(signal.SIGTERM)
        assert stop.is_set()
    finally:
        signal.signal(signal.SIGTERM, previous[0])
        signal.signal(signal.SIGINT, previous[1])
