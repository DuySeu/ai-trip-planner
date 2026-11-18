"""Daily weather for a trip from Open-Meteo: a forecast near today, last year's same dates beyond."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

import httpx

from domain.plan import Weather, WeatherBasis
from research.cache import Cache, cache_key
from utils.domain import ARCHIVE_URL, FORECAST_URL

logger = logging.getLogger(__name__)

PROVIDER = "open_meteo"
FORECAST_DAYS = 16
FORECAST_TTL = timedelta(hours=6)
ARCHIVE_TTL = timedelta(days=30)
TIMEOUT_S = 10.0
DAILY_FIELDS = "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
WMO_SUMMARY: Mapping[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Light freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Light snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


# Weather for each date from start to end: a forecast up to today + 15 days (cached 6 h), the same
# month and day one year earlier after that (cached 30 days). A failed call leaves its dates out.
def weather_for_trip(
    client: httpx.Client,
    cache: Cache,
    lat: float,
    lon: float,
    start: date,
    end: date,
    today: date,
) -> dict[date, Weather]:
    last_forecast_day = today + timedelta(days=FORECAST_DAYS - 1)
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # Each trip date maps to the date the provider is asked for
    forecast = {d: d for d in dates if d <= last_forecast_day}
    typical = {d: _year_ago(d) for d in dates if d > last_forecast_day}

    result: dict[date, Weather] = {}
    if forecast:
        result |= _fetch_days(
            client, cache, FORECAST_URL, (lat, lon), forecast, "forecast", FORECAST_TTL
        )
    if typical:
        result |= _fetch_days(
            client, cache, ARCHIVE_URL, (lat, lon), typical, "typical", ARCHIVE_TTL
        )
    return result


# The same month and day one year earlier; Feb 29 becomes Feb 28
def _year_ago(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


# Weather for the trip dates in wanted (trip date -> provider date) from one endpoint, via the cache
def _fetch_days(
    client: httpx.Client,
    cache: Cache,
    url: str,
    point: tuple[float, float],
    wanted: Mapping[date, date],
    basis: WeatherBasis,
    ttl: timedelta,
) -> dict[date, Weather]:
    first, last = min(wanted.values()), max(wanted.values())
    params: dict[str, Any] = {
        "latitude": point[0],
        "longitude": point[1],
        "daily": DAILY_FIELDS,
        "timezone": "auto",
        "start_date": first.isoformat(),
        "end_date": last.isoformat(),
    }
    key = cache_key(PROVIDER, url, params)

    # Look in the cache before calling the API; a bad answer is not cached
    body = cache.get(key)
    from_cache = body is not None
    try:
        if body is None:
            response = client.get(url, params=params, timeout=TIMEOUT_S)
            response.raise_for_status()
            body = response.json()
        days = _parse(body, wanted, basis)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
        logger.warning("weather from %s failed: %s", url, exc)
        return {}
    if not from_cache:
        cache.put(key, PROVIDER, f"{url} {first}..{last}", body, ttl)
    return days


# The wanted dates found in an Open-Meteo body; a day with a missing value is left out
def _parse(
    body: dict[str, Any], wanted: Mapping[date, date], basis: WeatherBasis
) -> dict[date, Weather]:
    daily = body["daily"]
    index = {day: i for i, day in enumerate(daily["time"])}
    days: dict[date, Weather] = {}
    for trip_date, source_date in wanted.items():
        i = index.get(source_date.isoformat())
        if i is None:
            continue
        t_max, t_min = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        precip, code = daily["precipitation_sum"][i], daily["weather_code"][i]
        if None in (t_max, t_min, precip, code):
            continue
        summary = WMO_SUMMARY.get(int(code), "Unknown")
        days[trip_date] = Weather(
            summary=summary,
            temp_min_c=float(t_min),
            temp_max_c=float(t_max),
            precip_mm=float(precip),
            basis=basis,
        )
    return days
