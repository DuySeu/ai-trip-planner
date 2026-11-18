"""Cache of provider responses: a Postgres-backed one for the app, an in-memory one for tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Protocol

from psycopg_pool import ConnectionPool

from db.repositories.research import cache_get, cache_put


# Where provider responses are kept between calls
class Cache(Protocol):
    # The payload stored under key, or None if missing or expired
    def get(self, key: str) -> dict[str, Any] | None: ...

    # Store a payload for ttl, replacing any older one under the same key
    def put(
        self, key: str, provider: str, query: str, payload: Mapping[str, Any], ttl: timedelta
    ) -> None: ...


# Stable key for one provider request: query case and spacing do not matter, param order does not
def cache_key(provider: str, query: str, params: Mapping[str, Any]) -> str:
    normalized = " ".join(query.casefold().split())
    raw = json.dumps([provider, normalized, params], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


# The search_cache table, each call in its own short transaction
class DbCache:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # The payload stored under key, or None if missing or expired
    def get(self, key: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            return cache_get(conn, key)

    # Store a payload for ttl, replacing any older one under the same key
    def put(
        self, key: str, provider: str, query: str, payload: Mapping[str, Any], ttl: timedelta
    ) -> None:
        with self._pool.connection() as conn:
            cache_put(conn, key, provider, query, payload, ttl)


# A cache that lives in memory and never expires; for tests, which read ttls to check the TTL used
class MemoryCache:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.ttls: dict[str, timedelta] = {}

    # The payload stored under key, or None
    def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    # Store a payload and remember its ttl
    def put(
        self, key: str, provider: str, query: str, payload: Mapping[str, Any], ttl: timedelta
    ) -> None:
        self.entries[key] = dict(payload)
        self.ttls[key] = ttl
