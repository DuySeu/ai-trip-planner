from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.exceptions import ResearchFailed
from research.cache import MemoryCache
from research.exchange_rates import vnd_rate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "er_api_thb.json"
TODAY = date(2026, 11, 17)


# A client whose transport answers every request with body and records the requests
def make_client(body: dict[str, Any] | None = None, status: int = 200):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status, text=json.dumps(body) if body is not None else FIXTURE.read_text()
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_vnd_rate_reads_vnd_per_unit_and_the_update_date():
    client, requests = make_client()

    rate, rate_date = vnd_rate(client, MemoryCache(), "THB", TODAY)

    assert (rate, rate_date) == (Decimal("760.015725"), date(2026, 11, 17))
    assert str(requests[0].url) == "https://open.er-api.com/v6/latest/THB"


def test_vnd_rate_uses_cache_on_second_call():
    client, requests = make_client()
    cache = MemoryCache()

    first = vnd_rate(client, cache, "THB", TODAY)
    second = vnd_rate(client, cache, "THB", TODAY)

    assert first == second and len(requests) == 1
    assert list(cache.ttls.values()) == [timedelta(hours=24)]


def test_vnd_rate_raises_research_failed_for_missing_currency():
    body = json.loads(FIXTURE.read_text())
    del body["rates"]["VND"]
    client, _ = make_client(body)
    with pytest.raises(ResearchFailed):
        vnd_rate(client, MemoryCache(), "THB", TODAY)


def test_vnd_rate_raises_research_failed_when_result_is_not_success():
    client, _ = make_client({"result": "error", "error-type": "unsupported-code"})
    with pytest.raises(ResearchFailed):
        vnd_rate(client, MemoryCache(), "THB", TODAY)


def test_vnd_rate_raises_research_failed_on_http_error():
    client, _ = make_client({}, status=503)
    with pytest.raises(ResearchFailed):
        vnd_rate(client, MemoryCache(), "THB", TODAY)


def test_vnd_rate_raises_research_failed_on_a_zero_rate():
    body = json.loads(FIXTURE.read_text())
    body["rates"]["VND"] = 0
    client, _ = make_client(body)
    with pytest.raises(ResearchFailed):
        vnd_rate(client, MemoryCache(), "THB", TODAY)


def test_vnd_rate_rejects_a_malformed_currency_code_without_a_request():
    client, requests = make_client()
    with pytest.raises(ValueError):
        vnd_rate(client, MemoryCache(), "../x", TODAY)
    assert requests == []
