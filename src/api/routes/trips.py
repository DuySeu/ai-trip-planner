"""Trip routes: create, read, retry, delete."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.exceptions import RequestValidationError

from api.deps import Conn, Deps, limit_trip_create, require_quota
from api.envelope import ApiResponse
from api.schemas.trips import CreateTripBody, TripCreated, TripOut, trip_out
from core.exceptions import Conflict, LimitExceeded, NotFound
from db.repositories import conversations, jobs, messages, trips, users
from domain.currency import local_currency_for
from domain.trip_request import today_in_vietnam, validate_request

router = APIRouter()


# POST /trips - Create a trip and queue its plan generation
@router.post(
    "/trips",
    status_code=202,
    dependencies=[Depends(limit_trip_create), Depends(require_quota("trip"))],
)
def create_trip(body: CreateTripBody, conn: Conn, deps: Deps) -> ApiResponse[TripCreated]:
    # Check the request against the rules that need today's date and the currency map
    problems = validate_request(body, today_in_vietnam(deps.now()))
    if problems:
        raise RequestValidationError(
            [{"loc": ("body",), "msg": problem, "type": "value_error"} for problem in problems]
        )

    # The user must exist and stay under the daily cap
    users.get_user(conn, body.user_id)
    if trips.count_trips_today(conn, body.user_id) >= deps.settings.user_trips_per_day:
        raise LimitExceeded("Daily trip limit reached for this name, try again tomorrow")

    # The trip and its job are written together, so a trip never waits without a job
    request = body.model_dump(mode="json", exclude={"user_id", "message_id"})
    trip = trips.create_trip(
        conn,
        body.user_id,
        request,
        local_currency_for(body.destination.country_code),
        deps.settings.retention_days,
    )
    jobs.enqueue(conn, trip.id)

    # A trip made from a chat form closes the form in the same transaction. A form already
    # used (two tabs) fails here, so the trip and job above are rolled back with it.
    if body.message_id is not None:
        form = messages.get_message(conn, body.message_id)
        owner = conversations.get_conversation(conn, form.conversation_id).user_id
        if owner != body.user_id:
            raise NotFound(f"message {body.message_id}")
        content = json.dumps({**request, "trip_id": str(trip.id)}, ensure_ascii=False)
        if messages.close_trip_form(conn, form.id, "created_trip", content) is None:
            raise Conflict("This form was already used")
        conversations.clear_draft(conn, form.conversation_id)

    conn.commit()
    return ApiResponse(success=True, data=TripCreated(id=trip.id, status=trip.status))


# GET /trips/{trip_id} - A trip with its status, stage and current plan
@router.get("/trips/{trip_id}")
def get_trip(trip_id: UUID, conn: Conn) -> ApiResponse[TripOut]:
    row = trips.get_trip(conn, trip_id)
    job = jobs.active_job(conn, trip_id)
    return ApiResponse(success=True, data=trip_out(row, job.stage if job else None))


# POST /trips/{trip_id}/retry - Queue generation again after a failure
@router.post(
    "/trips/{trip_id}/retry", status_code=202, dependencies=[Depends(require_quota("trip"))]
)
def retry_trip(trip_id: UUID, conn: Conn) -> ApiResponse[TripCreated]:
    row = trips.get_trip(conn, trip_id)
    if jobs.active_job(conn, trip_id) is not None:
        raise Conflict("A plan is already being made for this trip")
    if row.status != "failed":
        raise Conflict("Only a failed trip can be retried")

    trips.set_status(conn, trip_id, "queued")
    jobs.enqueue(conn, trip_id)
    conn.commit()
    return ApiResponse(success=True, data=TripCreated(id=trip_id, status="queued"))


# DELETE /trips/{trip_id} - Delete a trip and everything under it
@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: UUID, conn: Conn) -> Response:
    trips.delete_trip(conn, trip_id)
    conn.commit()
    return Response(status_code=204)
