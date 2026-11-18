"""VND per unit of a local currency, from the ExchangeRate-API open endpoint (no key, daily)."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from core.exceptions import ResearchFailed
from research.cache import Cache, cache_key
from utils.domain import RATES_URL

PROVIDER = "exchange_rate"
CACHE_TTL = timedelta(hours=24)
TIMEOUT_S = 10.0
CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


# VND per one unit of currency, and the date the provider updated it; cached 24 h.
# today is the date used when the response carries no update time.
# The endpoint is based on the local currency (not on VND), because rates per 1 VND are
# rounded to 6 decimals: 1 / 0.000039 for USD is off by 0.4 percent, for EUR by about 14.
def vnd_rate(
    client: httpx.Client, cache: Cache, currency: str, today: date
) -> tuple[Decimal, date]:
    if not CURRENCY_CODE.match(currency):
        raise ValueError(f"not a currency code: {currency!r}")

    # Look in the cache before calling the API
    key = cache_key(PROVIDER, f"{currency}/VND", {})
    payload = cache.get(key)
    if payload is None:
        payload = _parse(_fetch(client, currency), currency, today)
        cache.put(key, PROVIDER, f"{currency}/VND", payload, CACHE_TTL)

    return Decimal(payload["rate"]), date.fromisoformat(payload["date"])


# One request; floats stay exact as Decimal, any transport or HTTP error means no answer
def _fetch(client: httpx.Client, currency: str) -> dict[str, Any]:
    try:
        response = client.get(RATES_URL.format(base=currency), timeout=TIMEOUT_S)
        response.raise_for_status()
        body: dict[str, Any] = json.loads(response.text, parse_float=Decimal)
    except (httpx.HTTPError, ValueError) as exc:
        raise ResearchFailed(f"exchange rate request failed: {exc}") from exc
    return body


# The rate and its date from a response, as JSON-safe strings for the cache
def _parse(body: dict[str, Any], currency: str, today: date) -> dict[str, str]:
    if body.get("result") != "success":
        raise ResearchFailed(f"exchange rate result {body.get('result')!r} for {currency}")
    try:
        rate = Decimal(body["rates"]["VND"])
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ResearchFailed(f"no VND rate in the response for {currency}") from exc
    if rate <= 0:
        raise ResearchFailed(f"VND rate for {currency} is not positive")

    updated = body.get("time_last_update_unix")
    rate_date = datetime.fromtimestamp(updated, UTC).date() if isinstance(updated, int) else today
    return {"rate": str(rate), "date": rate_date.isoformat()}
