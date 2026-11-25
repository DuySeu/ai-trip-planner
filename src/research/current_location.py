"""The visitor's city and its weather now, from their coordinates: Nominatim and Open-Meteo.

The coordinates never reach the database or the logs: answers are cached in memory only."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

from core.exceptions import ResearchFailed
from domain.trip_request import Language
from research.weather import WMO_SUMMARY
from utils.domain import FORECAST_URL, REVERSE_GEOCODING_URL

logger = logging.getLogger(__name__)

CITY_TTL = timedelta(days=1)
WEATHER_TTL = timedelta(minutes=30)
TIMEOUT_S = 10.0
# Nominatim's usage policy asks for an identifying User-Agent and at most 1 request per second
USER_AGENT = "ai-trip-planner/0.1"
NOMINATIM_MIN_INTERVAL_S = 1.0
# A caller further back in the queue than this gets an error (503) instead of holding a thread
NOMINATIM_MAX_WAIT_S = 3.0
# About 1 km: nearby visitors share an answer, and the providers never see the exact point
COORD_DECIMALS = 2
# The address parts that name the place, most specific first
PLACE_FIELDS = ("city", "town", "village", "municipality", "county", "state")

# ponytail: one throttle per process, a shared limiter (Redis, a table) if the API runs replicas.
# Callers book the next free 1 s slot under the lock, then wait and call outside it
_nominatim_lock = threading.Lock()
_nominatim_next_slot = 0.0


@dataclass(frozen=True)
class CurrentWeather:
    temperature_c: float
    weather_code: int
    summary: str


# country_code is upper case
@dataclass(frozen=True)
class CurrentLocation:
    city: str
    country_code: str
    weather: CurrentWeather | None


# A small in-memory cache with a ttl per entry; past max_entries the oldest entry goes
class LocationCache:
    def __init__(
        self, max_entries: int = 1000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()

    # The value under key, or None if missing or expired
    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= self._clock():
                del self._entries[key]
                return None
            return value

    # Store value for ttl, dropping the oldest entries past max_entries
    def put(self, key: str, value: Any, ttl: timedelta) -> None:
        with self._lock:
            self._entries[key] = (self._clock() + ttl.total_seconds(), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


# The city around (lat, lon) and its weather now; raises ResearchFailed when no city is found.
# A weather failure keeps the city with weather None. Failures are never cached.
def current_location(
    client: httpx.Client, cache: LocationCache, lat: float, lon: float, language: Language
) -> CurrentLocation:
    lat, lon = round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)

    city_key = f"city:{lat}:{lon}:{language}"
    place: tuple[str, str] | None = cache.get(city_key)
    if place is None:
        place = _fetch_place(client, lat, lon, language)
        cache.put(city_key, place, CITY_TTL)

    weather_key = f"weather:{lat}:{lon}"
    weather: CurrentWeather | None = cache.get(weather_key)
    if weather is None:
        weather = _fetch_weather(client, lat, lon)
        if weather is not None:
            cache.put(weather_key, weather, WEATHER_TTL)

    return CurrentLocation(place[0], place[1], weather)


# (city, country code) from one Nominatim reverse call, waiting for its slot of the 1 request per
# second rule. Error messages name the failure only: httpx errors carry the URL, and with it the
# coordinates.
def _fetch_place(
    client: httpx.Client, lat: float, lon: float, language: Language
) -> tuple[str, str]:
    global _nominatim_next_slot
    params: dict[str, str | int | float] = {
        "format": "jsonv2",
        "zoom": 10,
        "lat": lat,
        "lon": lon,
        "accept-language": language,
    }
    # Book a slot; a long queue fails fast
    with _nominatim_lock:
        now = time.monotonic()
        slot = max(now, _nominatim_next_slot)
        if slot - now > NOMINATIM_MAX_WAIT_S:
            logger.warning("reverse geocoding busy")
            raise ResearchFailed("reverse geocoding is busy")
        _nominatim_next_slot = slot + NOMINATIM_MIN_INTERVAL_S
    time.sleep(slot - now)

    try:
        response = client.get(
            REVERSE_GEOCODING_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("reverse geocoding failed: %s", type(exc).__name__)
        raise ResearchFailed(f"reverse geocoding failed: {type(exc).__name__}") from exc

    address = body.get("address") or {}
    city = next((address[f] for f in PLACE_FIELDS if address.get(f)), None)
    country = address.get("country_code")
    if not city or not country:
        raise ResearchFailed("reverse geocoding found no city")
    return str(city), str(country).upper()


# The weather now from Open-Meteo, or None when the call or its answer fails
def _fetch_weather(client: httpx.Client, lat: float, lon: float) -> CurrentWeather | None:
    params: dict[str, str | float] = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code",
        "timezone": "auto",
    }
    try:
        response = client.get(FORECAST_URL, params=params, timeout=TIMEOUT_S)
        response.raise_for_status()
        current = response.json()["current"]
        code = int(current["weather_code"])
        temperature = float(current["temperature_2m"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("current weather failed: %s", type(exc).__name__)
        return None
    return CurrentWeather(temperature, code, WMO_SUMMARY.get(code, "Unknown"))
