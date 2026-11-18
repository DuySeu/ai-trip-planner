"""Request and response bodies of the user routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from db.repositories.users import UserRow
from domain.trip_request import normalize_name


# Body of POST /users; a bad name is a 422
class ClaimUserBody(BaseModel):
    name: str

    # NFC, trimmed, 1 to 50 characters
    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return normalize_name(value)


# A user and how many trips they have
class UserOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    trip_count: int


# The public view of a user row
def user_out(row: UserRow, trip_count: int) -> UserOut:
    return UserOut(id=row.id, name=row.name, created_at=row.created_at, trip_count=trip_count)
