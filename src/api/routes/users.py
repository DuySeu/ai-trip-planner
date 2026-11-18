"""User routes: claim a name, look a user up, list their trips."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from api.deps import Conn
from api.envelope import ApiResponse, PageMeta
from api.schemas.trips import TripSummary, trip_summary
from api.schemas.users import ClaimUserBody, UserOut, user_out
from db.repositories import trips, users

router = APIRouter()

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# POST /users - Claim a name, or return the existing user for that name
@router.post("/users")
def claim_user(body: ClaimUserBody, conn: Conn) -> ApiResponse[UserOut]:
    row = users.claim_user(conn, body.name)
    conn.commit()
    return ApiResponse(success=True, data=user_out(row, trips.count_trips(conn, row.id)))


# GET /users/{user_id} - A user and their trip count
@router.get("/users/{user_id}")
def get_user(user_id: UUID, conn: Conn) -> ApiResponse[UserOut]:
    row = users.get_user(conn, user_id)
    return ApiResponse(success=True, data=user_out(row, trips.count_trips(conn, row.id)))


# GET /users/{user_id}/trips - A user's trips, newest first, paged
@router.get("/users/{user_id}/trips")
def list_user_trips(
    user_id: UUID,
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[list[TripSummary]]:
    users.get_user(conn, user_id)
    rows = trips.list_trips(conn, user_id, limit, offset)
    return ApiResponse(
        success=True,
        data=[trip_summary(row) for row in rows],
        meta=PageMeta(total=trips.count_trips(conn, user_id), limit=limit, offset=offset),
    )
