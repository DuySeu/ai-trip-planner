from __future__ import annotations

from datetime import timedelta

from research.cache import DbCache


def test_db_cache_returns_stored_payload_until_it_expires(db_pool):
    cache = DbCache(db_pool)
    cache.put("k1", "exchange_rate", "THB/VND", {"rate": "760"}, timedelta(hours=1))
    cache.put("k2", "exchange_rate", "USD/VND", {"rate": "25000"}, timedelta(seconds=-1))

    assert cache.get("k1") == {"rate": "760"}
    assert cache.get("k2") is None
    assert cache.get("missing") is None
