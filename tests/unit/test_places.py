from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.exceptions import ResearchFailed
from research.cache import MemoryCache, cache_key
from research.places import Place, search_places

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "geocoding_da_lat.json"


# A client whose transport answers every request with body and records the requests
def make_client(body: dict[str, Any] | None = None, status: int = 200):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status, json=body if body is not None else json.loads(FIXTURE.read_text())
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_search_places_maps_results_and_drops_unknown_countries():
    body = json.loads(FIXTURE.read_text())
    body["results"][1]["country_code"] = "ZZ"
    client, requests = make_client(body)

    places = search_places(client, MemoryCache(), "Da Lat", "en")

    assert places == [Place("Da Lat", "Lam Dong", "VN", 11.94646, 108.44193)]
    params = requests[0].url.params
    assert (params["name"], params["count"], params["language"]) == ("Da Lat", "10", "en")
    assert requests[0].url.host == "geocoding-api.open-meteo.com"


def test_search_places_keeps_non_ascii_names_and_missing_admin1():
    body = {
        "results": [
            {"name": "Đà Nẵng", "latitude": 16.06, "longitude": 108.2, "country_code": "vn"}
        ]
    }
    client, _ = make_client(body)

    assert search_places(client, MemoryCache(), "Da Nang", "vi") == [
        Place("Đà Nẵng", None, "VN", 16.06, 108.2)
    ]


def test_search_places_uses_cache_on_second_call():
    client, requests = make_client()
    cache = MemoryCache()

    first = search_places(client, cache, "Da Lat", "en")
    second = search_places(client, cache, "  da  lat ", "en")

    assert first == second and len(requests) == 1
    assert list(cache.ttls.values()) == [timedelta(days=30)]


def test_search_places_returns_empty_list_when_response_has_no_results_key():
    client, _ = make_client({"generationtime_ms": 0.1})
    assert search_places(client, MemoryCache(), "zzzqqxx", "en") == []


def test_search_places_with_blank_query_makes_no_request():
    client, requests = make_client()
    assert search_places(client, MemoryCache(), "   ", "en") == [] and requests == []


def test_search_places_raises_research_failed_on_http_error():
    client, _ = make_client({}, status=500)
    with pytest.raises(ResearchFailed):
        search_places(client, MemoryCache(), "Da Lat", "en")


def test_cache_key_ignores_case_and_extra_spaces():
    a = cache_key("open_meteo_geocoding", "Da  Lat ", {"language": "en", "count": 10})
    b = cache_key("open_meteo_geocoding", " da lat", {"count": 10, "language": "en"})
    assert a == b
    assert a != cache_key("open_meteo_geocoding", "da lat", {"language": "vi", "count": 10})
    assert a != cache_key("tavily", "da lat", {"language": "en", "count": 10})
