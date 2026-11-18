from __future__ import annotations

import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from domain.trip_request import (
    TripRequest,
    budget_total_vnd,
    clean_text,
    normalize_name,
    today_in_vietnam,
    validate_request,
)

TODAY = date(2026, 11, 17)
FIELDS: dict[str, Any] = {
    "destination": {"name": "Da Lat", "country_code": "VN", "lat": 11.94, "lon": 108.44},
    "origin": "Ho Chi Minh City",
    "start_date": "2026-12-20",
    "end_date": "2026-12-23",
    "travelers": 4,
    "travel_styles": ["nature"],
    "budget_amount": "5000000",
    "budget_scope": "per_person",
}


def request(**overrides: Any) -> TripRequest:
    return TripRequest.model_validate({**FIELDS, **overrides})


def test_today_in_vietnam_is_next_day_at_0030_local_when_utc_is_previous_day():
    assert today_in_vietnam(datetime(2026, 11, 16, 17, 30, tzinfo=UTC)) == date(2026, 11, 17)


def test_today_in_vietnam_rejects_naive_datetime():
    with pytest.raises(ValueError):
        today_in_vietnam(datetime(2026, 11, 16, 17, 30))


def test_validate_request_accepts_start_today_and_rejects_yesterday():
    assert validate_request(request(start_date="2026-11-17", end_date="2026-11-18"), TODAY) == []
    errors = validate_request(request(start_date="2026-11-16", end_date="2026-11-18"), TODAY)
    assert len(errors) == 1 and "start_date" in errors[0]


def test_validate_request_rejects_trip_longer_than_30_days():
    assert validate_request(request(start_date="2026-12-01", end_date="2026-12-30"), TODAY) == []
    assert validate_request(request(start_date="2026-12-01", end_date="2026-12-31"), TODAY)


def test_validate_request_rejects_end_before_start():
    assert validate_request(request(end_date="2026-12-19"), TODAY)


def test_validate_request_rejects_unknown_country():
    destination = {**FIELDS["destination"], "country_code": "ZZ"}
    errors = validate_request(request(destination=destination), TODAY)
    assert len(errors) == 1 and "ZZ" in errors[0]


def test_styles_must_not_be_empty_or_unknown():
    with pytest.raises(ValidationError):
        request(travel_styles=[])
    with pytest.raises(ValidationError):
        request(travel_styles=["skydiving"])


def test_request_rejects_out_of_range_numbers():
    for overrides in ({"travelers": 0}, {"travelers": 51}, {"budget_amount": "0"}):
        with pytest.raises(ValidationError):
            request(**overrides)


def test_budget_total_vnd_multiplies_per_person_by_travelers():
    assert budget_total_vnd(request()) == Decimal("20000000")
    assert budget_total_vnd(request(budget_scope="total")) == Decimal("5000000")


def test_request_cleans_text_fields():
    r = request(origin="  Ha\x00 Noi ", notes="  \n ")
    assert r.origin == "Ha Noi" and r.notes is None
    with pytest.raises(ValidationError):
        request(notes="x" * 2001)
    with pytest.raises(ValidationError):
        request(origin="   ")


def test_request_dumps_to_json_and_back():
    r = request(notes="line 1\nline 2")
    assert TripRequest.model_validate(r.model_dump(mode="json")) == r


def test_clean_text_keeps_line_breaks_and_drops_other_controls():
    assert clean_text(" a\tb\nc\x07 ", 10) == "a\tb\nc"


def test_normalize_name_turns_nfd_into_nfc():
    assert normalize_name(unicodedata.normalize("NFD", " Đức ")) == unicodedata.normalize(
        "NFC", "Đức"
    )


def test_normalize_name_rejects_blank_and_over_50_chars():
    with pytest.raises(ValueError):
        normalize_name("  ")
    with pytest.raises(ValueError):
        normalize_name("x" * 51)
