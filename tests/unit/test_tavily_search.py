from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.exceptions import QuotaExhausted, ResearchFailed
from research.cache import MemoryCache
from service.tavily.search import MAX_SNIPPET_CHARS, SearchHit, tavily_search
from tests.fakes import FakeSink

NOW = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
QUOTA = "usage limit"


# Records every search and answers with a scripted body or raises a scripted error
class FakeTavily:
    def __init__(self, body: dict[str, Any] | Exception | None = None) -> None:
        self.body = {"results": []} if body is None else body
        self.calls: list[tuple[str, int]] = []
        self.domains: list[list[str] | None] = []

    def search(
        self, query: str, max_results: int = 5, include_domains: list[str] | None = None
    ) -> dict[str, Any]:
        self.calls.append((query, max_results))
        self.domains.append(include_domains)
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def result(n: int, content: str = "text") -> dict[str, Any]:
    return {"title": f"T{n}", "url": f"https://example.com/{n}", "content": content, "score": 0.9}


def test_tavily_search_maps_and_trims_results():
    client = FakeTavily({"results": [result(1, "x" * 2000), result(2, "a  b\n c")]})

    hits = tavily_search(client, MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW)

    assert hits == [
        SearchHit("T1", "https://example.com/1", "x" * MAX_SNIPPET_CHARS),
        SearchHit("T2", "https://example.com/2", "a b c"),
    ]
    assert client.calls == [("q", 5)]


def test_tavily_search_drops_results_without_url_or_content():
    body = {"results": [{"title": "t", "content": "c"}, {"title": "t", "url": "u", "content": ""}]}

    assert tavily_search(FakeTavily(body), MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW) == []


def test_tavily_search_uses_cache_for_24_hours():
    client, cache = FakeTavily({"results": [result(1)]}), MemoryCache()

    first = tavily_search(client, cache, FakeSink(), "Hotels  in Da Lat", 5, QUOTA, NOW)
    second = tavily_search(client, cache, FakeSink(), "hotels in da lat", 5, QUOTA, NOW)

    assert first == second and len(client.calls) == 1
    assert list(cache.ttls.values()) == [timedelta(hours=24)]


def test_quota_error_blocks_tavily_until_next_month_and_raises():
    sink = FakeSink()
    client = FakeTavily(Exception("This request exceeds your plan's set Usage Limit."))

    with pytest.raises(QuotaExhausted) as raised:
        tavily_search(client, MemoryCache(), sink, "q", 5, QUOTA, NOW)

    assert raised.value.blocked_until == datetime(2026, 12, 1, tzinfo=UTC)
    assert sink.blocked_until("tavily") == datetime(2026, 12, 1, tzinfo=UTC)


def test_block_rolls_over_the_year_in_december():
    sink = FakeSink()
    client = FakeTavily(Exception("usage limit"))
    december = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)

    with pytest.raises(QuotaExhausted) as raised:
        tavily_search(client, MemoryCache(), sink, "q", 5, QUOTA, december)

    assert raised.value.blocked_until == datetime(2027, 1, 1, tzinfo=UTC)


def test_other_error_raises_research_failed_without_blocking():
    sink = FakeSink()

    with pytest.raises(ResearchFailed):
        tavily_search(FakeTavily(TimeoutError("slow")), MemoryCache(), sink, "q", 5, QUOTA, NOW)

    assert sink.blocks == {}


def test_malformed_response_raises_research_failed_and_is_not_cached():
    cache = MemoryCache()

    with pytest.raises(ResearchFailed):
        tavily_search(FakeTavily({"detail": "x"}), cache, FakeSink(), "q", 5, QUOTA, NOW)

    assert cache.entries == {}


def test_active_block_raises_without_calling_tavily():
    sink, client = FakeSink(), FakeTavily({"results": [result(1)]})
    sink.block("tavily", NOW + timedelta(days=3), "usage limit")

    with pytest.raises(QuotaExhausted):
        tavily_search(client, MemoryCache(), sink, "q", 5, QUOTA, NOW)

    assert client.calls == []


def test_cached_query_is_served_while_blocked():
    sink, cache = FakeSink(), MemoryCache()
    client = FakeTavily({"results": [result(1)]})
    tavily_search(client, cache, sink, "q", 5, QUOTA, NOW)
    sink.block("tavily", NOW + timedelta(days=3), "usage limit")

    assert len(tavily_search(client, cache, sink, "q", 5, QUOTA, NOW)) == 1


def test_include_domains_are_sent_to_the_client():
    client = FakeTavily({"results": [result(1)]})

    tavily_search(client, MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW, ("a.com", "b.com"))

    assert client.domains == [["a.com", "b.com"]]


def test_no_include_domains_means_the_client_gets_none():
    client = FakeTavily({"results": [result(1)]})

    tavily_search(client, MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW)

    assert client.domains == [None]


def test_an_empty_allowlist_search_runs_again_over_the_whole_web():
    class OpenWebOnly(FakeTavily):
        def search(self, query, max_results=5, include_domains=None):
            self.body = {"results": [] if include_domains else [result(1)]}
            return super().search(query, max_results, include_domains)

    client = OpenWebOnly()

    hits = tavily_search(client, MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW, ("a.com",))

    assert [h.url for h in hits] == ["https://example.com/1"]
    assert client.domains == [["a.com"], None]


def test_an_allowlist_search_with_results_is_not_run_again():
    client = FakeTavily({"results": [result(1)]})

    tavily_search(client, MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW, ("a.com",))

    assert len(client.calls) == 1


def test_a_search_with_no_allowlist_and_no_results_is_not_run_again():
    client = FakeTavily({"results": []})

    assert tavily_search(client, MemoryCache(), FakeSink(), "q", 5, QUOTA, NOW) == []
    assert len(client.calls) == 1


def test_cache_keeps_allowlisted_and_open_searches_apart():
    client, cache = FakeTavily({"results": [result(1)]}), MemoryCache()

    tavily_search(client, cache, FakeSink(), "q", 5, QUOTA, NOW, ("a.com",))
    tavily_search(client, cache, FakeSink(), "q", 5, QUOTA, NOW)

    assert client.domains == [["a.com"], None]
