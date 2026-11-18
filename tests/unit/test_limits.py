from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from api.limits import RateLimiter, client_ip
from core.exceptions import LimitExceeded

START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


# A clock the test moves by hand
class Clock:
    def __init__(self, at: datetime = START) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> None:
        self.at += timedelta(**delta)


def make_request(headers: dict[str, str], client: tuple[str, int] | None = ("10.0.0.1", 5000)):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_limiter_allows_burst_then_blocks_within_minute():
    clock = Clock()
    limiter = RateLimiter(per_minute=3, per_day=100, now=clock)
    for _ in range(3):
        limiter.hit("1.1.1.1")
    with pytest.raises(LimitExceeded):
        limiter.hit("1.1.1.1")

    # Another key is not affected, and the bucket refills with time
    limiter.hit("2.2.2.2")
    clock.advance(seconds=20)
    limiter.hit("1.1.1.1")
    with pytest.raises(LimitExceeded):
        limiter.hit("1.1.1.1")


def test_limiter_daily_counter_resets_next_utc_day():
    clock = Clock(datetime(2026, 11, 17, 23, 0, tzinfo=UTC))
    limiter = RateLimiter(per_minute=100, per_day=2, now=clock)
    limiter.hit("k")
    limiter.hit("k")
    with pytest.raises(LimitExceeded):
        limiter.hit("k")

    clock.advance(hours=1)
    limiter.hit("k")
    limiter.hit("k")
    with pytest.raises(LimitExceeded):
        limiter.hit("k")


def test_refused_hit_does_not_use_up_the_day():
    clock = Clock()
    limiter = RateLimiter(per_minute=1, per_day=2, now=clock)
    limiter.hit("k")
    for _ in range(5):
        with pytest.raises(LimitExceeded):
            limiter.hit("k")
    clock.advance(minutes=1)
    limiter.hit("k")


def test_limiter_keeps_at_most_max_keys_entries():
    limiter = RateLimiter(per_minute=5, per_day=5, now=Clock(), max_keys=3)
    for i in range(10):
        limiter.hit(f"ip-{i}")
    assert len(limiter._entries) == 3
    assert list(limiter._entries) == ["ip-7", "ip-8", "ip-9"]


def test_limiter_drops_idle_keys_from_a_past_day():
    clock = Clock()
    limiter = RateLimiter(per_minute=5, per_day=5, now=clock)
    limiter.hit("old")
    clock.advance(days=1)
    limiter.hit("new")
    assert list(limiter._entries) == ["new"]


def test_client_ip_ignores_forwarded_header_unless_trusted():
    request = make_request({"X-Forwarded-For": "9.9.9.9, 10.1.1.1"})
    assert client_ip(request, trust_proxy_headers=False) == "10.0.0.1"
    assert client_ip(request, trust_proxy_headers=True) == "9.9.9.9"


def test_client_ip_falls_back_to_socket_when_trusted_header_is_missing_or_blank():
    assert client_ip(make_request({}), trust_proxy_headers=True) == "10.0.0.1"
    assert client_ip(make_request({"X-Forwarded-For": " "}), trust_proxy_headers=True) == "10.0.0.1"
    assert client_ip(make_request({}, client=None), trust_proxy_headers=False) == "unknown"
