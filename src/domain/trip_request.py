"""The trip request from the form or the chat, and its rules."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from domain.currency import local_currency_for

VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_TRIP_DAYS = 30
NAME_MAX_LEN = 50
PLACE_MAX_LEN = 200
NOTES_MAX_LEN = 2000
VIETNAMESE_LETTER = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE
)
# Control characters kept in free text: line breaks and tabs from a textarea
KEPT_CONTROLS = {"\n", "\t"}

TravelStyle = Literal[
    "relax", "adventure", "culture", "food", "nature", "nightlife", "shopping", "luxury", "budget"
]
TransportMode = Literal["flight", "train", "bus", "car", "motorbike", "boat"]
Language = Literal["en", "vi"]
BudgetScope = Literal["per_person", "total"]


# NFC-normalize, drop control characters, trim; raise if longer than max_len
def clean_text(value: str, max_len: int) -> str:
    normalized = unicodedata.normalize("NFC", value)
    kept = "".join(
        ch for ch in normalized if ch in KEPT_CONTROLS or unicodedata.category(ch) != "Cc"
    )
    cleaned = kept.strip()
    if len(cleaned) > max_len:
        raise ValueError(f"must be at most {max_len} characters")
    return cleaned


# "vi" when the text has a Vietnamese letter, else "en".
# ponytail: a diacritics check; Vietnamese typed without accents gets English, add a detector if it matters
def language_of(text: str) -> Language:
    return "vi" if VIETNAMESE_LETTER.search(text) else "en"


# A user name as stored: NFC, trimmed, 1 to 50 characters
def normalize_name(name: str) -> str:
    cleaned = clean_text(name, NAME_MAX_LEN)
    if not cleaned:
        raise ValueError("name must not be empty")
    return cleaned


# Clean a required single place or origin field
def _clean_place(value: str) -> str:
    cleaned = clean_text(value, PLACE_MAX_LEN)
    if not cleaned:
        raise ValueError("must not be empty")
    return cleaned


PlaceText = Annotated[str, AfterValidator(_clean_place)]


# A place picked from the place search
class Destination(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: PlaceText
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


# What the visitor asked for; cross-field rules live in validate_request
class TripRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: Destination
    origin: PlaceText
    start_date: date
    end_date: date
    travelers: int = Field(ge=1, le=50)
    travel_styles: tuple[TravelStyle, ...] = Field(min_length=1)
    # Both null: no budget given, the planner picks a sensible cost and the plan's total is its suggestion
    budget_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    budget_scope: BudgetScope | None = None
    language: Language = "en"
    notes: str | None = None

    # Blank notes are no notes
    @field_validator("notes")
    @classmethod
    def _clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_text(value, NOTES_MAX_LEN) or None

    # Drop repeated styles, keeping the first order
    @field_validator("travel_styles")
    @classmethod
    def _dedupe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))

    # An amount needs its scope and a scope needs its amount
    @model_validator(mode="after")
    def _budget_pair(self) -> TripRequest:
        if (self.budget_amount is None) != (self.budget_scope is None):
            raise ValueError("budget_amount and budget_scope are given together or not at all")
        return self


# Rules that need more than one field or today's date; empty means valid
def validate_request(request: TripRequest, today: date) -> list[str]:
    errors = []
    if request.start_date < today:
        errors.append(f"start_date must be today ({today.isoformat()}) or later")
    if request.end_date < request.start_date:
        errors.append("end_date must not be before start_date")
    elif request.end_date - request.start_date >= timedelta(days=MAX_TRIP_DAYS):
        errors.append(f"a trip lasts at most {MAX_TRIP_DAYS} days")
    try:
        local_currency_for(request.destination.country_code)
    except ValueError:
        errors.append(f"destination country {request.destination.country_code} is not supported")
    return errors


# Today's date in Vietnam, whatever the server's time zone
def today_in_vietnam(now: datetime) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(VIETNAM_TZ).date()


# The whole group's budget in VND; None when the visitor left the budget to the planner
def budget_total_vnd(request: TripRequest) -> Decimal | None:
    if request.budget_amount is None:
        return None
    if request.budget_scope == "per_person":
        return request.budget_amount * request.travelers
    return request.budget_amount
