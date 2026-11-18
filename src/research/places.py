"""Destination search for the trip form, on the Open-Meteo geocoding API (no key)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

from core.constants import COUNTRY_CURRENCY
from core.exceptions import ResearchFailed
from domain.trip_request import Language
from research.cache import Cache, cache_key
from utils.domain import GEOCODING_URL

PROVIDER = "open_meteo_geocoding"
RESULT_COUNT = 10
CACHE_TTL = timedelta(days=30)
TIMEOUT_S = 10.0


# One search hit; country_code is upper case and always a key of COUNTRY_CURRENCY
@dataclass(frozen=True)
class Place:
    name: str
    admin1: str | None
    country_code: str
    lat: float
    lon: float


# Places matching q in the given language, cached 30 days; hits in countries we have no currency for are dropped
def search_places(client: httpx.Client, cache: Cache, q: str, language: Language) -> list[Place]:
    query = " ".join(q.split())
    if not query:
        return []

    # Look in the cache before calling the API
    params = {"count": RESULT_COUNT, "language": language}
    key = cache_key(PROVIDER, query, params)
    payload = cache.get(key)
    if payload is None:
        payload = _fetch(client, query, params)
        cache.put(key, PROVIDER, query, payload, CACHE_TTL)

    results: list[dict[str, Any]] = payload.get("results", [])
    return [
        Place(r["name"], r.get("admin1"), r["country_code"].upper(), r["latitude"], r["longitude"])
        for r in results
        if r.get("country_code", "").upper() in COUNTRY_CURRENCY
        and {"name", "latitude", "longitude"} <= r.keys()
    ]


# One geocoding request; any transport or HTTP error means no answer
def _fetch(client: httpx.Client, query: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = client.get(GEOCODING_URL, params={"name": query, **params}, timeout=TIMEOUT_S)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ResearchFailed(f"place search failed: {exc}") from exc
    return body
