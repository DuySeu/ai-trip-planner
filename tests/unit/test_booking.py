from __future__ import annotations

from datetime import date, timedelta

from domain.booking import BookingDates, dates_errors, dates_from
from domain.trip_request import TripRequest

TODAY = date(2026, 11, 21)


def D(days: int) -> date:
    return TODAY + timedelta(days=days)


def trip() -> TripRequest:
    return TripRequest.model_validate(
        {
            "destination": {"name": "Da Lat", "country_code": "VN", "lat": 11.94, "lon": 108.44},
            "origin": "Hà Nội",
            "start_date": D(30).isoformat(),
            "end_date": D(33).isoformat(),
            "travelers": 2,
            "travel_styles": ["nature"],
            "budget_amount": "5000000",
            "budget_scope": "per_person",
        }
    )


def test_hotel_dates_need_check_out_after_check_in():
    assert dates_errors("hotel", BookingDates(check_in=D(10), check_out=D(10)), TODAY) != []
    assert dates_errors("hotel", BookingDates(check_in=D(10), check_out=D(12)), TODAY) == []


def test_hotel_needs_both_dates_and_none_in_the_past():
    assert dates_errors("hotel", BookingDates(check_in=D(10)), TODAY) != []
    assert dates_errors("hotel", BookingDates(check_in=D(-1), check_out=D(2)), TODAY) != []


def test_hotel_stay_longer_than_30_nights_is_rejected():
    assert dates_errors("hotel", BookingDates(check_in=D(1), check_out=D(32)), TODAY) != []
    assert dates_errors("hotel", BookingDates(check_in=D(1), check_out=D(31)), TODAY) == []


def test_flight_needs_only_a_future_depart_date():
    assert dates_errors("flight", BookingDates(depart=D(5)), TODAY) == []
    assert dates_errors("flight", BookingDates(), TODAY) != []
    assert dates_errors("flight", BookingDates(depart=D(-1)), TODAY) != []
    assert dates_errors("flight", BookingDates(depart=D(5), return_=D(4)), TODAY) != []


def test_return_reads_from_its_json_name():
    assert BookingDates.model_validate(
        {"depart": "2026-12-01", "return": "2026-12-05"}
    ).return_ == (date(2026, 12, 5))


def test_dates_from_prefers_the_open_trip_over_the_draft():
    draft = {"start_date": D(3).isoformat(), "end_date": D(5).isoformat()}
    assert dates_from("hotel", draft, trip()) == BookingDates(check_in=D(30), check_out=D(33))
    assert dates_from("hotel", draft, None) == BookingDates(check_in=D(3), check_out=D(5))
    assert dates_from("flight", draft, None) == BookingDates(depart=D(3), return_=D(5))


def test_dates_from_is_none_when_the_search_lacks_dates():
    assert dates_from("hotel", {"start_date": D(3).isoformat()}, None) is None
    assert dates_from("hotel", None, None) is None
    assert dates_from("flight", {"start_date": D(3).isoformat()}, None) == BookingDates(depart=D(3))
