from __future__ import annotations

import dataclasses
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg_pool import ConnectionPool

from tests.integration.test_api_foundation import make_app
from tests.unit.test_current_location import CITY_BODY, NOMINATIM_HOST, WEATHER_BODY

HCMC = {"lat": 10.776889, "lon": 106.700806, "language": "vi"}


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("research.current_location.NOMINATIM_MIN_INTERVAL_S", 0.0)


# A client whose Nominatim answers city_body and whose Open-Meteo answers WEATHER_BODY, or 500
def weather_client(
    pool: ConnectionPool,
    city_body: dict[str, Any] | None = None,
    weather_status: int = 200,
) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == NOMINATIM_HOST:
            return httpx.Response(200, json=CITY_BODY if city_body is None else city_body)
        return httpx.Response(weather_status, json=WEATHER_BODY)

    app = make_app(pool)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    app.state.deps = dataclasses.replace(app.state.deps, http=client)
    return TestClient(app, raise_server_exceptions=False)


def test_current_weather_returns_city_and_weather(db_pool):
    response = weather_client(db_pool).get("/weather/current", params=HCMC)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "city": "Thành phố Hồ Chí Minh",
        "country_code": "VN",
        "weather": {"temperature_c": 28.4, "weather_code": 1, "summary": "Mainly clear"},
    }


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 91, "lon": 106.7},
        {"lat": 10.7, "lon": -181},
        {"lon": 106.7},
        {"lat": "abc", "lon": 106.7},
        {"lat": 10.7, "lon": 106.7, "language": "fr"},
    ],
)
def test_current_weather_rejects_bad_parameters(db_pool, params):
    response = weather_client(db_pool).get("/weather/current", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_current_weather_returns_503_when_city_unknown(db_pool):
    response = weather_client(db_pool, city_body={"error": "Unable to geocode"}).get(
        "/weather/current", params=HCMC
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


def test_current_weather_keeps_city_when_weather_fails(db_pool):
    response = weather_client(db_pool, weather_status=500).get("/weather/current", params=HCMC)
    assert response.status_code == 200
    assert response.json()["data"]["city"] == "Thành phố Hồ Chí Minh"
    assert response.json()["data"]["weather"] is None


def test_current_weather_writes_nothing_to_search_cache(db_pool, db_conn: Connection[Any]):
    count = "SELECT count(*) FROM search_cache"
    before = db_conn.execute(count).fetchone()
    weather_client(db_pool).get("/weather/current", params=HCMC)
    assert db_conn.execute(count).fetchone() == before
