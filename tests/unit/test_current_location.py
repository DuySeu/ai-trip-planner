from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx
import pytest

from core.exceptions import ResearchFailed
from research.current_location import (
    USER_AGENT,
    CurrentLocation,
    CurrentWeather,
    LocationCache,
    current_location,
)

NOMINATIM_HOST = "nominatim.openstreetmap.org"
FORECAST_HOST = "api.open-meteo.com"
LAT, LON = 10.776889, 106.700806
# Shape of a real Nominatim reverse answer at zoom 10 (trimmed)
CITY_BODY = {
    "address": {
        "suburb": "Phường Sài Gòn",
        "city": "Thành phố Hồ Chí Minh",
        "country": "Việt Nam",
        "country_code": "vn",
    }
}
WEATHER_BODY = {"current": {"time": "2026-11-25T15:30", "temperature_2m": 28.4, "weather_code": 1}}


# A clock the test moves by hand
class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# A client answering Nominatim with city_body and Open-Meteo with WEATHER_BODY; failing hosts answer 500
def make_client(city_body: dict[str, Any] | None = None, failing: tuple[str, ...] = ()):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host in failing:
            return httpx.Response(500, text="boom")
        if request.url.host == NOMINATIM_HOST:
            return httpx.Response(200, json=CITY_BODY if city_body is None else city_body)
        return httpx.Response(200, json=WEATHER_BODY)

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("research.current_location.NOMINATIM_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr("research.current_location._nominatim_next_slot", 0.0)


def hosts(requests: list[httpx.Request]) -> list[str]:
    return [r.url.host for r in requests]


# What this module logged (httpx's own request lines are redacted by the app's formatter)
def own_log(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(
        r.getMessage() for r in caplog.records if r.name == "research.current_location"
    )


def test_returns_city_and_current_weather():
    client, _ = make_client()
    found = current_location(client, LocationCache(), LAT, LON, "vi")
    assert found == CurrentLocation(
        "Thành phố Hồ Chí Minh", "VN", CurrentWeather(28.4, 1, "Mainly clear")
    )


@pytest.mark.parametrize(
    ("address", "city"),
    [
        ({"town": "Sa Pa", "state": "Lào Cai", "country_code": "vn"}, "Sa Pa"),
        ({"village": "Mai Châu", "country_code": "vn"}, "Mai Châu"),
        ({"county": "Huyện Côn Đảo", "country_code": "vn"}, "Huyện Côn Đảo"),
        ({"state": "Tỉnh Lâm Đồng", "country_code": "vn"}, "Tỉnh Lâm Đồng"),
    ],
)
def test_falls_back_to_town_village_county_then_state(address: dict[str, str], city: str):
    client, _ = make_client({"address": address})
    assert current_location(client, LocationCache(), LAT, LON, "vi").city == city


@pytest.mark.parametrize(
    "body", [{"address": {"country_code": "vn"}}, {"error": "Unable to geocode"}, {}]
)
def test_raises_research_failed_when_address_has_no_place_name(body: dict[str, Any]):
    client, _ = make_client(body)
    with pytest.raises(ResearchFailed):
        current_location(client, LocationCache(), LAT, LON, "vi")


def test_raises_research_failed_when_nominatim_fails():
    client, _ = make_client(failing=(NOMINATIM_HOST,))
    with pytest.raises(ResearchFailed):
        current_location(client, LocationCache(), LAT, LON, "vi")


def test_weather_failure_keeps_city_with_weather_none():
    client, _ = make_client(failing=(FORECAST_HOST,))
    found = current_location(client, LocationCache(), LAT, LON, "vi")
    assert found.city == "Thành phố Hồ Chí Minh"
    assert found.weather is None


def test_rounds_coordinates_before_calling_providers():
    client, requests = make_client()
    current_location(client, LocationCache(), LAT, LON, "vi")
    city, weather = requests
    assert (city.url.params["lat"], city.url.params["lon"]) == ("10.78", "106.7")
    assert (weather.url.params["latitude"], weather.url.params["longitude"]) == ("10.78", "106.7")


def test_nearby_points_share_one_provider_call():
    client, requests = make_client()
    cache = LocationCache()
    current_location(client, cache, 10.7761, 106.7, "vi")
    current_location(client, cache, 10.7759, 106.7, "vi")
    assert hosts(requests) == [NOMINATIM_HOST, FORECAST_HOST]


def test_weather_refetched_after_30_minutes_city_kept_for_a_day():
    client, requests = make_client()
    clock = FakeClock()
    cache = LocationCache(clock=clock)
    current_location(client, cache, LAT, LON, "vi")
    clock.now += timedelta(minutes=31).total_seconds()
    current_location(client, cache, LAT, LON, "vi")
    assert hosts(requests).count(NOMINATIM_HOST) == 1
    assert hosts(requests).count(FORECAST_HOST) == 2


def test_failed_city_is_not_cached():
    client, requests = make_client({"address": {}})
    cache = LocationCache()
    for _ in range(2):
        with pytest.raises(ResearchFailed):
            current_location(client, cache, LAT, LON, "vi")
    assert hosts(requests).count(NOMINATIM_HOST) == 2


def test_sends_user_agent_and_accept_language():
    client, requests = make_client()
    current_location(client, LocationCache(), LAT, LON, "en")
    city = requests[0]
    assert city.headers["User-Agent"] == USER_AGENT
    assert city.url.params["accept-language"] == "en"


def test_failure_log_does_not_contain_coordinates(caplog: pytest.LogCaptureFixture):
    client, _ = make_client(failing=(NOMINATIM_HOST, FORECAST_HOST))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ResearchFailed) as raised:
        current_location(client, LocationCache(), LAT, LON, "vi")
    for text in (own_log(caplog), str(raised.value)):
        assert "10.78" not in text
        assert "106.7" not in text


def test_weather_failure_log_does_not_contain_coordinates(caplog: pytest.LogCaptureFixture):
    client, _ = make_client(failing=(FORECAST_HOST,))
    caplog.set_level(logging.DEBUG)
    current_location(client, LocationCache(), LAT, LON, "vi")
    logged = own_log(caplog)
    assert "weather" in logged
    assert "10.78" not in logged
    assert "106.7" not in logged


def test_cache_drops_oldest_entry_past_max_entries():
    cache = LocationCache(max_entries=2)
    for key in ("a", "b", "c"):
        cache.put(key, key, timedelta(hours=1))
    assert cache.get("a") is None
    assert (cache.get("b"), cache.get("c")) == ("b", "c")


def test_cache_entry_expires_after_its_ttl():
    clock = FakeClock()
    cache = LocationCache(clock=clock)
    cache.put("k", 1, timedelta(minutes=30))
    clock.now += timedelta(minutes=29).total_seconds()
    assert cache.get("k") == 1
    clock.now += timedelta(minutes=2).total_seconds()
    assert cache.get("k") is None


def test_busy_reverse_geocoding_fails_fast_instead_of_queueing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("research.current_location.NOMINATIM_MIN_INTERVAL_S", 60.0)
    client, requests = make_client()
    cache = LocationCache()
    current_location(client, cache, LAT, LON, "vi")
    # The next free slot is a minute away, past the longest wait
    with pytest.raises(ResearchFailed):
        current_location(client, cache, 21.03, 105.85, "vi")
    assert hosts(requests).count(NOMINATIM_HOST) == 1
