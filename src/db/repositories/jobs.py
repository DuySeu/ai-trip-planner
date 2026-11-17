"""Plan generation jobs: queue, lease, progress, finish."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection, errors
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from core.exceptions import Conflict
from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "jobs.sql")


# One row of jobs; request is the re-plan's new TripRequest dict, if any
@dataclass(frozen=True)
class JobRow:
    id: UUID
    trip_id: UUID
    kind: str
    status: str
    stage: str | None
    attempts: int
    max_attempts: int
    llm_calls_used: int
    run_after: datetime
    leased_until: datetime | None
    request: dict[str, Any] | None
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None


# Queue a job; Conflict if the trip already has a queued or running one
def enqueue(
    conn: Connection[Any],
    trip_id: UUID,
    kind: str = "generate_plan",
    request: Mapping[str, Any] | None = None,
) -> JobRow:
    params = {
        "trip_id": trip_id,
        "kind": kind,
        "request": None if request is None else Jsonb(request),
    }
    try:
        with conn.cursor(row_factory=class_row(JobRow)) as cur:
            row = cur.execute(QUERIES["enqueue"], params).fetchone()
    except errors.UniqueViolation as e:
        raise Conflict(f"trip {trip_id} already has an active job") from e
    assert row is not None  # INSERT ... RETURNING always returns the row
    return row


# Take the next due job (or one whose lease expired) for lease_seconds; None when idle
def lease_next(conn: Connection[Any], worker_id: str, lease_seconds: int) -> JobRow | None:
    # worker_id is not stored (no column): the lease time alone decides who may run the job
    with conn.cursor(row_factory=class_row(JobRow)) as cur:
        return cur.execute(QUERIES["lease_next"], {"lease_seconds": lease_seconds}).fetchone()


# Record the stage the job is in, for progress
def set_stage(conn: Connection[Any], job_id: UUID, stage: str) -> None:
    conn.execute(QUERIES["set_stage"], {"id": job_id, "stage": stage})


# Add LLM calls made by an attempt to the job's running total
def add_llm_calls(conn: Connection[Any], job_id: UUID, n: int) -> None:
    conn.execute(QUERIES["add_llm_calls"], {"id": job_id, "n": n})


# End the job as succeeded or failed and release its lease
def finish(conn: Connection[Any], job_id: UUID, status: str, last_error: str | None = None) -> None:
    conn.execute(QUERIES["finish"], {"id": job_id, "status": status, "last_error": last_error})


# Put the job back in the queue to run again after run_after
def requeue(conn: Connection[Any], job_id: UUID, run_after: datetime, last_error: str) -> None:
    params = {"id": job_id, "run_after": run_after, "last_error": last_error}
    conn.execute(QUERIES["requeue"], params)


# The trip's queued or running job, if any
def active_job(conn: Connection[Any], trip_id: UUID) -> JobRow | None:
    with conn.cursor(row_factory=class_row(JobRow)) as cur:
        return cur.execute(QUERIES["active_job"], {"trip_id": trip_id}).fetchone()
