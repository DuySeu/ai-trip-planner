"""Trips: the request columns, status and the current plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from core.exceptions import NotFound, PlanConflict
from db.queries import QUERIES_DIR, load_queries

QUERIES = load_queries(QUERIES_DIR / "trips.sql")


# One row of trips; plan is the raw JSONB, validated by the caller
@dataclass(frozen=True)
class TripRow:
    id: UUID
    user_id: UUID
    destination_name: str
    destination_country: str
    destination_lat: float
    destination_lon: float
    origin: str
    start_date: date
    end_date: date
    travelers: int
    group_type: str
    travel_styles: list[str]
    transport_modes: list[str]
    conversation_id: UUID | None
    budget_amount: Decimal
    budget_scope: str
    local_currency: str | None
    language: str
    notes: str | None
    status: str
    failure_reason: str | None
    plan: dict[str, Any] | None
    total_cost_vnd: Decimal | None
    over_budget: bool | None
    model_id: str | None
    plan_revision: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


# Insert a queued trip from a TripRequest dict (model_dump(mode="json") shape)
def create_trip(
    conn: Connection[Any],
    user_id: UUID,
    request: Mapping[str, Any],
    local_currency: str | None,
    retention_days: int,
    conversation_id: UUID | None = None,
) -> TripRow:
    params = {
        **_request_params(request),
        "user_id": user_id,
        "conversation_id": conversation_id,
        "local_currency": local_currency,
        "retention_days": retention_days,
    }
    with conn.cursor(row_factory=class_row(TripRow)) as cur:
        row = cur.execute(QUERIES["create_trip"], params).fetchone()
    assert row is not None  # INSERT ... RETURNING always returns the row
    return row


# Fetch a trip by id
def get_trip(conn: Connection[Any], trip_id: UUID) -> TripRow:
    with conn.cursor(row_factory=class_row(TripRow)) as cur:
        row = cur.execute(QUERIES["get_trip"], {"id": trip_id}).fetchone()
    if row is None:
        raise NotFound(f"trip {trip_id}")
    return row


# One page of a user's trips, newest first
def list_trips(conn: Connection[Any], user_id: UUID, limit: int, offset: int) -> list[TripRow]:
    params = {"user_id": user_id, "limit": limit, "offset": offset}
    with conn.cursor(row_factory=class_row(TripRow)) as cur:
        return cur.execute(QUERIES["list_trips"], params).fetchall()


# Set the trip status; failure_reason is cleared unless given
def set_status(
    conn: Connection[Any], trip_id: UUID, status: str, failure_reason: str | None = None
) -> None:
    params = {"id": trip_id, "status": status, "failure_reason": failure_reason}
    if conn.execute(QUERIES["set_status"], params).rowcount == 0:
        raise NotFound(f"trip {trip_id}")


# Mark the trip as used now and push its expiry retention_days ahead
def touch(conn: Connection[Any], trip_id: UUID, retention_days: int) -> None:
    params = {"id": trip_id, "retention_days": retention_days}
    if conn.execute(QUERIES["touch"], params).rowcount == 0:
        raise NotFound(f"trip {trip_id}")


# Delete a trip; jobs and research rows go with it
def delete_trip(conn: Connection[Any], trip_id: UUID) -> None:
    if conn.execute(QUERIES["delete_trip"], {"id": trip_id}).rowcount == 0:
        raise NotFound(f"trip {trip_id}")


# Trips the user created since midnight in Vietnam
def count_trips_today(conn: Connection[Any], user_id: UUID) -> int:
    row = conn.execute(QUERIES["count_trips_today"], {"user_id": user_id}).fetchone()
    assert row is not None
    return int(row[0])


# Overwrite the plan if the trip is still at base_revision; a request replaces the request columns too
def save_plan(
    conn: Connection[Any],
    trip_id: UUID,
    base_revision: int,
    plan: Mapping[str, Any],
    total_cost_vnd: Decimal,
    over_budget: bool,
    model_id: str | None,
    request: Mapping[str, Any] | None = None,
) -> TripRow:
    params = {
        "id": trip_id,
        "base_revision": base_revision,
        "plan": Jsonb(plan),
        "total_cost_vnd": total_cost_vnd,
        "over_budget": over_budget,
        "model_id": model_id,
    }
    query = QUERIES["save_plan"]
    if request is not None:
        params = {**params, **_request_params(request)}
        query = QUERIES["save_plan_with_request"]

    with conn.cursor(row_factory=class_row(TripRow)) as cur:
        row = cur.execute(query, params).fetchone()
    if row is None:
        get_trip(conn, trip_id)  # raises NotFound for a missing trip
        raise PlanConflict(f"trip {trip_id} is no longer at revision {base_revision}")
    return row


# Flatten a TripRequest dict into the trips request columns
def _request_params(request: Mapping[str, Any]) -> dict[str, Any]:
    destination = request["destination"]
    return {
        "destination_name": destination["name"],
        "destination_country": destination["country_code"],
        "destination_lat": destination["lat"],
        "destination_lon": destination["lon"],
        "origin": request["origin"],
        "start_date": date.fromisoformat(str(request["start_date"])),
        "end_date": date.fromisoformat(str(request["end_date"])),
        "travelers": request["travelers"],
        "group_type": request["group_type"],
        "travel_styles": list(request["travel_styles"]),
        "transport_modes": list(request.get("transport_modes") or []),
        "budget_amount": Decimal(str(request["budget_amount"])),
        "budget_scope": request["budget_scope"],
        "language": request.get("language", "en"),
        "notes": request.get("notes"),
    }
