"""The dates a hotel or flight search needs, where they come from, and their rules."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from domain.trip_request import MAX_TRIP_DAYS, TripRequest

BookingKind = Literal["hotel", "flight"]
# A day/month date in a message, with an optional four-digit year: 25/12, 25/12/2026
DATE_IN_TEXT = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])")


# Hotel stays use check_in/check_out; flights use depart and an optional return
class BookingDates(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    check_in: date | None = None
    check_out: date | None = None
    depart: date | None = None
    return_: date | None = Field(default=None, alias="return")


# What is wrong with the dates for this kind of search; empty when they are fine
def dates_errors(kind: BookingKind, dates: BookingDates, today: date) -> list[str]:
    if kind == "hotel":
        if dates.check_in is None or dates.check_out is None:
            return ["check_in and check_out are required"]
        errors = [] if dates.check_in >= today else ["check_in must not be in the past"]
        nights = (dates.check_out - dates.check_in).days
        if nights <= 0:
            errors.append("check_out must be after check_in")
        elif nights > MAX_TRIP_DAYS:
            errors.append(f"a stay must be at most {MAX_TRIP_DAYS} nights")
        return errors
    if dates.depart is None:
        return ["depart is required"]
    errors = [] if dates.depart >= today else ["depart must not be in the past"]
    if dates.return_ is not None and dates.return_ < dates.depart:
        errors.append("return must not be before depart")
    return errors


# The dates said in the message, else of the open trip, else of the conversation's draft; None
# when the search lacks them. Said dates count only when they are enough: two for a stay, one for
# a ticket
def dates_from(
    kind: BookingKind,
    request_draft: Mapping[str, Any] | None,
    trip: TripRequest | None,
    said: Sequence[date] = (),
) -> BookingDates | None:
    start: date | None
    end: date | None
    if len(said) >= (2 if kind == "hotel" else 1):
        start, end = said[0], said[1] if len(said) > 1 else None
    elif trip is not None:
        start, end = trip.start_date, trip.end_date
    else:
        draft = BookingDates.model_validate(
            {
                "check_in": (request_draft or {}).get("start_date"),
                "check_out": (request_draft or {}).get("end_date"),
            }
        )
        start, end = draft.check_in, draft.check_out
    if kind == "hotel":
        return None if start is None or end is None else BookingDates(check_in=start, check_out=end)
    return None if start is None else BookingDates.model_validate({"depart": start, "return": end})


# The day/month dates written in text, in order. A date without a year is the next one on or after
# the date before it (today for the first), so "30/12 to 02/01" crosses the new year; impossible
# dates are skipped
# ponytail: only d/m[/yyyy]; "25-27/12" or "Dec 25" still ask with the dates card
def dates_in_text(text: str, today: date) -> list[date]:
    found: list[date] = []
    for day, month, year in DATE_IN_TEXT.findall(text):
        base = int(year) if year else today.year
        try:
            when = date(base, int(month), int(day))
            if not year and when < (found[-1] if found else today):
                when = date(base + 1, int(month), int(day))
        except ValueError:
            continue
        found.append(when)
    return found
