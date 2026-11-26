"""Request and response bodies of the trip routes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from db.repositories.trips import TripRow
from domain.trip_request import Destination, TripRequest


# Body of POST /trips: the trip request plus who it is for; the local currency is never sent.
# message_id is the chat trip form this trip is made from, if any
class CreateTripBody(TripRequest):
    user_id: UUID
    message_id: UUID | None = None


# What POST /trips and POST /trips/{id}/retry return: where to poll
class TripCreated(BaseModel):
    id: UUID
    status: str


# One line of a trip list
class TripSummary(BaseModel):
    id: UUID
    destination: Destination
    start_date: date
    end_date: date
    travelers: int
    status: str
    total_cost_vnd: Decimal | None
    over_budget: bool | None
    created_at: datetime
    updated_at: datetime


# A trip with its request, progress and current plan
class TripOut(TripSummary):
    origin: str
    travel_styles: list[str]
    budget_amount: Decimal | None
    budget_scope: str | None
    local_currency: str | None
    language: str
    notes: str | None
    stage: str | None
    failure_reason: str | None
    plan_revision: int
    plan: dict[str, Any] | None


# The place a trip row holds
def _destination(row: TripRow) -> Destination:
    return Destination(
        name=row.destination_name,
        country_code=row.destination_country,
        lat=row.destination_lat,
        lon=row.destination_lon,
    )


# The list view of a trip row
def trip_summary(row: TripRow) -> TripSummary:
    return TripSummary(
        id=row.id,
        destination=_destination(row),
        start_date=row.start_date,
        end_date=row.end_date,
        travelers=row.travelers,
        status=row.status,
        total_cost_vnd=row.total_cost_vnd,
        over_budget=row.over_budget,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# The full view of a trip row; stage is the running job's stage, if any
def trip_out(row: TripRow, stage: str | None) -> TripOut:
    return TripOut(
        **trip_summary(row).model_dump(),
        origin=row.origin,
        travel_styles=row.travel_styles,
        budget_amount=row.budget_amount,
        budget_scope=row.budget_scope,
        local_currency=row.local_currency,
        language=row.language,
        notes=row.notes,
        stage=stage,
        failure_reason=row.failure_reason,
        plan_revision=row.plan_revision,
        plan=row.plan,
    )


# The request a trip row was made from
def trip_request(row: TripRow) -> TripRequest:
    return TripRequest.model_validate(
        {
            "destination": _destination(row),
            "origin": row.origin,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "travelers": row.travelers,
            "travel_styles": row.travel_styles,
            "budget_amount": row.budget_amount,
            "budget_scope": row.budget_scope,
            "language": row.language,
            "notes": row.notes,
        }
    )
