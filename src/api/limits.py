"""In-process rate limits per key (client IP): a token bucket per minute and a counter per UTC day."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from threading import Lock

from fastapi import Request

from core.exceptions import LimitExceeded

SECONDS_PER_MINUTE = 60.0
# Memory bound: at most MAX_KEYS entries (about 100 bytes each), least recently hit evicted first
MAX_KEYS = 10_000


# What one key has used: bucket tokens at last_seen, and hits counted on one UTC day
@dataclass
class _Entry:
    tokens: float
    last_seen: datetime
    day: date
    day_hits: int


# Allow up to per_minute hits in a burst, refilled evenly over a minute, and per_day hits per UTC day
class RateLimiter:
    def __init__(
        self,
        per_minute: int,
        per_day: int,
        now: Callable[[], datetime],
        max_keys: int = MAX_KEYS,
    ) -> None:
        self._per_minute = per_minute
        self._per_day = per_day
        self._now = now
        self._max_keys = max_keys
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = Lock()

    # Count one hit for the key, or raise LimitExceeded; a refused hit uses nothing
    def hit(self, key: str) -> None:
        now = self._now()
        with self._lock:
            self._evict_idle(now)
            entry = self._entries.get(key) or _Entry(
                tokens=float(self._per_minute), last_seen=now, day=now.date(), day_hits=0
            )

            # Refill the bucket for the time since the last hit, and start a new day's count
            elapsed = max((now - entry.last_seen).total_seconds(), 0.0)
            tokens = min(
                float(self._per_minute),
                entry.tokens + elapsed * self._per_minute / SECONDS_PER_MINUTE,
            )
            day_hits = entry.day_hits if entry.day == now.date() else 0

            # Refuse without changing the stored entry
            if day_hits >= self._per_day:
                raise LimitExceeded("Daily limit reached, try again tomorrow")
            if tokens < 1.0:
                raise LimitExceeded("Too many requests, try again in a minute")

            self._entries[key] = _Entry(tokens - 1.0, now, now.date(), day_hits + 1)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_keys:
                self._entries.popitem(last=False)

    # Drop the least recently hit keys that hold no information: a full bucket and a past day
    def _evict_idle(self, now: datetime) -> None:
        while self._entries:
            key, entry = next(iter(self._entries.items()))
            idle = (now - entry.last_seen).total_seconds()
            if entry.day == now.date() or idle < SECONDS_PER_MINUTE:
                return
            del self._entries[key]


# The caller's IP: first X-Forwarded-For entry only behind a trusted proxy, else the socket address
def client_ip(request: Request, trust_proxy_headers: bool) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if trust_proxy_headers and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
