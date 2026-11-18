from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from research.cache import MemoryCache
from research.weather import FORECAST_DAYS, weather_for_trip

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TODAY = date(2026, 11, 17)
LAT, LON = 11.9404, 108.4583


# An Open-Meteo body for the requested dates, in the shape of the recorded fixture;
# temp_max is the day of month and temp_min the month, so a test can tell which date was read
def body_for(fixture: str, start: date, end: date) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / fixture).read_text())
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    body["daily"] = {
        "time": [d.isoformat() for d in days],
        "temperature_2m_max": [float(d.day) for d in days],
        "temperature_2m_min": [float(d.month) for d in days],
        "precipitation_sum": [1.5 for _ in days],
        "weather_code": [61 for _ in days],
    }
    return body


# A client whose forecast and archive hosts answer from body_for; failing hosts answer 500
def make_client(failing: tuple[str, ...] = ()):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        host = request.url.host
        if host in failing:
            return httpx.Response(500, text="boom")
        fixture = (
            "open_meteo_forecast.json"
            if host == "api.open-meteo.com"
            else "open_meteo_archive.json"
        )
        start = date.fromisoformat(request.url.params["start_date"])
        end = date.fromisoformat(request.url.params["end_date"])
        return httpx.Response(200, json=body_for(fixture, start, end))

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_forecast_window_is_sixteen_days():
    assert FORECAST_DAYS == 16


def test_trip_inside_forecast_window_is_all_forecast():
    client, requests = make_client()
    start = TODAY + timedelta(days=2)

    result = weather_for_trip(
        client, MemoryCache(), LAT, LON, start, start + timedelta(days=3), TODAY
    )

    assert len(result) == 4
    assert {w.basis for w in result.values()} == {"forecast"}
    assert [r.url.host for r in requests] == ["api.open-meteo.com"]
    params = requests[0].url.params
    assert params["daily"] == "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
    assert params["timezone"] == "auto"
    assert (params["latitude"], params["longitude"]) == (str(LAT), str(LON))


def test_weather_is_built_from_the_response_values():
    client, _ = make_client()
    start = TODAY + timedelta(days=3)

    weather = weather_for_trip(client, MemoryCache(), LAT, LON, start, start, TODAY)[start]

    assert weather.summary == "Light rain"
    assert (weather.temp_max_c, weather.temp_min_c, weather.precip_mm) == (20.0, 11.0, 1.5)


def test_trip_crossing_forecast_window_gets_both_bases():
    client, _ = make_client()
    start, end = TODAY + timedelta(days=10), TODAY + timedelta(days=19)

    w = weather_for_trip(client, MemoryCache(), LAT, LON, start, end, TODAY)

    assert len(w) == 10
    assert {w[d].basis for d in w} == {"forecast", "typical"}
    assert w[TODAY + timedelta(days=15)].basis == "forecast"
    assert w[TODAY + timedelta(days=16)].basis == "typical"


def test_typical_days_read_the_same_month_and_day_one_year_earlier():
    client, requests = make_client()
    start, end = TODAY + timedelta(days=33), TODAY + timedelta(days=35)  # 2026-12-20 .. 2026-12-22

    w = weather_for_trip(client, MemoryCache(), LAT, LON, start, end, TODAY)

    assert [r.url.host for r in requests] == ["archive-api.open-meteo.com"]
    assert requests[0].url.params["start_date"] == "2025-12-20"
    assert requests[0].url.params["end_date"] == "2025-12-22"
    assert {w[d].basis for d in w} == {"typical"}
    assert w[date(2026, 12, 21)].temp_max_c == 21.0


def test_feb_29_falls_back_to_feb_28_last_year():
    client, requests = make_client()
    today = date(2028, 1, 10)

    w = weather_for_trip(
        client, MemoryCache(), LAT, LON, date(2028, 2, 29), date(2028, 3, 1), today
    )

    assert requests[0].url.params["start_date"] == "2027-02-28"
    assert requests[0].url.params["end_date"] == "2027-03-01"
    assert w[date(2028, 2, 29)].temp_max_c == 28.0
    assert w[date(2028, 3, 1)].temp_max_c == 1.0


def test_failed_call_returns_empty_for_those_dates():
    client, _ = make_client(failing=("api.open-meteo.com", "archive-api.open-meteo.com"))

    w = weather_for_trip(client, MemoryCache(), LAT, LON, TODAY, TODAY + timedelta(days=20), TODAY)

    assert w == {}


def test_failed_forecast_keeps_the_typical_days():
    client, _ = make_client(failing=("api.open-meteo.com",))

    w = weather_for_trip(client, MemoryCache(), LAT, LON, TODAY, TODAY + timedelta(days=20), TODAY)

    assert set(w) == {TODAY + timedelta(days=i) for i in range(16, 21)}
    assert {x.basis for x in w.values()} == {"typical"}


def test_days_without_values_are_left_out():
    def handler(request: httpx.Request) -> httpx.Response:
        body = body_for("open_meteo_forecast.json", TODAY, TODAY + timedelta(days=1))
        body["daily"]["temperature_2m_max"][0] = None
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    w = weather_for_trip(client, MemoryCache(), LAT, LON, TODAY, TODAY + timedelta(days=1), TODAY)

    assert list(w) == [TODAY + timedelta(days=1)]


def test_malformed_body_returns_empty_and_is_not_cached():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"daily": {}}))
    )
    cache = MemoryCache()

    assert weather_for_trip(client, cache, LAT, LON, TODAY, TODAY, TODAY) == {}
    assert cache.entries == {}


def test_second_call_is_served_from_cache_with_the_right_ttls():
    client, requests = make_client()
    cache = MemoryCache()
    start, end = TODAY + timedelta(days=10), TODAY + timedelta(days=19)

    first = weather_for_trip(client, cache, LAT, LON, start, end, TODAY)
    second = weather_for_trip(client, cache, LAT, LON, start, end, TODAY)

    assert first == second and len(requests) == 2
    assert sorted(cache.ttls.values()) == [timedelta(hours=6), timedelta(days=30)]
