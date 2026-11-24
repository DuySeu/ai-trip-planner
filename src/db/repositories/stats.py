"""Dashboard numbers: system health now and usage over the last days.

Only counts and grouped labels (destination, model, intent) come out, never names, ids, notes or error
text, because the stats routes have no authentication. Health windows use the database clock; "today"
for LLM calls is the UTC day, like the quota ceiling. Usage ranges are the last `days` Vietnam calendar
days, today included.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import class_row, dict_row

from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "stats.sql")


# How many rows have one value (an outcome, status, intent, style or form status)
@dataclass(frozen=True)
class Count:
    key: str
    count: int


# A provider refused until blocked_until
@dataclass(frozen=True)
class Block:
    service: str
    blocked_until: datetime


# The latest failed job: the trip's failure reason code, not the raw error
@dataclass(frozen=True)
class LastFailure:
    reason: str | None
    finished_at: datetime


# LLM calls since 00:00 UTC and the two ceilings they are checked against
@dataclass(frozen=True)
class LlmToday:
    calls: int
    input_tokens: int
    output_tokens: int
    ceiling_new_trips: int
    ceiling_chat: int


# LLM calls in the last hour
@dataclass(frozen=True)
class LlmLastHour:
    calls: int
    errors: int
    outcomes: list[Count]
    p50_latency_ms: float | None
    p95_latency_ms: float | None


# Jobs waiting or running now
@dataclass(frozen=True)
class JobQueue:
    queued: int
    running: int
    oldest_queued_s: int | None


# Jobs that finished in the last 24 hours; plan time includes the wait in the queue
@dataclass(frozen=True)
class PlansLastDay:
    succeeded: int
    p50_s: float | None
    p95_s: float | None
    failed: int
    last_failure: LastFailure | None


# GET /stats/health
@dataclass(frozen=True)
class HealthStats:
    generated_at: datetime
    llm_today: LlmToday
    llm_last_hour: LlmLastHour
    jobs: JobQueue
    plans_last_day: PlansLastDay
    blocks: list[Block]


# Users in total, created in the range, and seen in the range
@dataclass(frozen=True)
class UserCounts:
    total: int
    new: int
    active: int


# Trips created in the range
@dataclass(frozen=True)
class TripCounts:
    created: int
    by_status: list[Count]
    domestic: int
    abroad: int
    avg_days: float | None
    avg_travelers: float | None
    median_budget_per_person_vnd: float | None
    with_plan: int
    over_budget: int


# Trips created and user messages sent on one Vietnam day
@dataclass(frozen=True)
class DayCount:
    day: date
    trips: int
    messages: int


# Trips to one destination
@dataclass(frozen=True)
class Destination:
    name: str
    country: str
    trips: int


# LLM calls of one model
@dataclass(frozen=True)
class ModelCount:
    model_id: str
    calls: int
    errors: int


# GET /stats/usage
@dataclass(frozen=True)
class UsageStats:
    days: int
    users: UserCounts
    trips: TripCounts
    daily: list[DayCount]
    conversations: int
    messages: int
    intents: list[Count]
    trip_forms: list[Count]
    destinations: list[Destination]
    styles: list[Count]
    models: list[ModelCount]


# The health numbers, with the configured LLM ceilings next to today's count
def health(conn: Connection[Any], ceiling_new_trips: int, ceiling_chat: int) -> HealthStats:
    today = _one(conn, "llm_today")
    hour = _one(conn, "llm_last_hour")
    plans = _one(conn, "plans_last_day")
    with conn.cursor(row_factory=class_row(LastFailure)) as cur:
        last_failure = cur.execute(QUERIES["last_failure"]).fetchone()
    with conn.cursor(row_factory=class_row(Block)) as cur:
        blocks = cur.execute(QUERIES["active_blocks"]).fetchall()
    now = conn.execute("SELECT now()").fetchone()
    assert now is not None

    return HealthStats(
        generated_at=now[0],
        llm_today=LlmToday(**today, ceiling_new_trips=ceiling_new_trips, ceiling_chat=ceiling_chat),
        llm_last_hour=LlmLastHour(**hour, outcomes=_counts(conn, "llm_outcomes_last_hour", {})),
        jobs=JobQueue(**_one(conn, "job_queue")),
        plans_last_day=PlansLastDay(**plans, last_failure=last_failure),
        blocks=blocks,
    )


# The usage numbers for the last `days` Vietnam days
def usage(conn: Connection[Any], days: int) -> UsageStats:
    params = {"days": days}
    chat = _one(conn, "chat_counts", params)
    with conn.cursor(row_factory=class_row(DayCount)) as cur:
        daily = cur.execute(QUERIES["daily"], params).fetchall()
    with conn.cursor(row_factory=class_row(Destination)) as cur:
        destinations = cur.execute(QUERIES["destinations"], params).fetchall()
    with conn.cursor(row_factory=class_row(ModelCount)) as cur:
        models = cur.execute(QUERIES["models"], params).fetchall()

    return UsageStats(
        days=days,
        users=UserCounts(**_one(conn, "user_counts", params)),
        trips=TripCounts(
            **_one(conn, "trip_counts", params), by_status=_counts(conn, "trip_statuses", params)
        ),
        daily=daily,
        conversations=chat["conversations"],
        messages=chat["messages"],
        intents=_counts(conn, "intents", params),
        trip_forms=_counts(conn, "trip_forms", params),
        destinations=destinations,
        styles=_counts(conn, "styles", params),
        models=models,
    )


# The single row of an aggregate query, as a dict
def _one(conn: Connection[Any], name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(QUERIES[name], params).fetchone()
    assert row is not None  # an aggregate without GROUP BY always returns one row
    return row


# The (key, count) rows of a grouping query
def _counts(conn: Connection[Any], name: str, params: dict[str, Any]) -> list[Count]:
    with conn.cursor(row_factory=class_row(Count)) as cur:
        return cur.execute(QUERIES[name], params).fetchall()
