"""Web search for the whole project: one Tavily client, cached 24 h, with the quota block."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg_pool import ConnectionPool

from core.exceptions import QuotaExhausted, ResearchFailed
from core.settings import Settings
from db.call_sink import DbCallSink
from models.model_router import CallSink
from research.cache import Cache, DbCache, cache_key
from service.tavily.client import TavilyClient, create_client
from utils.domain import SEARCH_DOMAINS, SearchTask

SERVICE = "tavily"
PROVIDER = "tavily"
CACHE_TTL = timedelta(hours=24)
SEARCH_MAX_RESULTS = 5
MAX_SNIPPET_CHARS = 500
MAX_ERROR_CHARS = 300


# One search result as the planner sees it; content is cut to MAX_SNIPPET_CHARS
@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    content: str


# One query and the task it is for in, hits out: the call any part of the backend makes to search
# the web. The task picks the domains the search may read.
WebSearch = Callable[[str, SearchTask], list[SearchHit]]


# The web search with the real client, the database cache and the quota block behind it
def build_web_search(
    settings: Settings, pool: ConnectionPool, now: Callable[[], datetime]
) -> WebSearch:
    client = create_client(settings.tavily_api_key)
    cache = DbCache(pool)
    sink = DbCallSink(pool)

    def search(query: str, task: SearchTask) -> list[SearchHit]:
        return tavily_search(
            client,
            cache,
            sink,
            query,
            SEARCH_MAX_RESULTS,
            settings.tavily_quota_pattern,
            now(),
            SEARCH_DOMAINS.get(task, ()),
        )

    return search


# Results for query, cached 24 h. A quota error blocks the service until the first day of next
# month (Tavily's free credits are monthly) and raises QuotaExhausted; other errors raise
# ResearchFailed. A cached query is served even while the service is blocked. With include_domains
# only those domains may answer; when they give nothing the query runs again over the whole web.
def tavily_search(
    client: TavilyClient,
    cache: Cache,
    sink: CallSink,
    query: str,
    max_results: int,
    quota_pattern: str,
    now: datetime,
    include_domains: Sequence[str] = (),
) -> list[SearchHit]:
    hits = _search_once(
        client, cache, sink, query, max_results, quota_pattern, now, include_domains
    )
    if not hits and include_domains:
        hits = _search_once(client, cache, sink, query, max_results, quota_pattern, now, ())
    return hits


# One search through the cache and the quota block
def _search_once(
    client: TavilyClient,
    cache: Cache,
    sink: CallSink,
    query: str,
    max_results: int,
    quota_pattern: str,
    now: datetime,
    include_domains: Sequence[str],
) -> list[SearchHit]:
    params: dict[str, Any] = {"max_results": max_results}
    if include_domains:
        params["include_domains"] = sorted(include_domains)
    key = cache_key(PROVIDER, query, params)
    payload = cache.get(key)
    if payload is None:
        # Refuse while blocked, then call Tavily
        until = sink.blocked_until(SERVICE)
        if until is not None and until > now:
            raise QuotaExhausted(until)
        payload = _fetch(client, sink, query, max_results, quota_pattern, now, include_domains)
        cache.put(key, PROVIDER, query, payload, CACHE_TTL)
    return [SearchHit(h["title"], h["url"], h["content"]) for h in payload["hits"]]


# One Tavily call; the third-party client raises its own error types, so any failure is mapped here
def _fetch(
    client: TavilyClient,
    sink: CallSink,
    query: str,
    max_results: int,
    quota_pattern: str,
    now: datetime,
    include_domains: Sequence[str],
) -> dict[str, Any]:
    try:
        if include_domains:
            response = client.search(
                query, max_results=max_results, include_domains=list(include_domains)
            )
        else:
            response = client.search(query, max_results=max_results)
    except Exception as exc:
        if re.search(quota_pattern, str(exc), re.IGNORECASE):
            until = _first_of_next_month(now)
            sink.block(SERVICE, until, str(exc)[:MAX_ERROR_CHARS])
            raise QuotaExhausted(until) from exc
        raise ResearchFailed(f"web search failed: {exc}"[:MAX_ERROR_CHARS]) from exc

    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list):
        raise ResearchFailed("web search answered without a results list")
    return {"hits": _trim(results)}


# Hits with a url and text, text cut to MAX_SNIPPET_CHARS
def _trim(results: Sequence[Any]) -> list[dict[str, str]]:
    hits = []
    for r in results:
        if not isinstance(r, dict):
            continue
        url, content = r.get("url"), " ".join(str(r.get("content") or "").split())
        if isinstance(url, str) and url and content:
            hits.append(
                {
                    "title": str(r.get("title") or ""),
                    "url": url,
                    "content": content[:MAX_SNIPPET_CHARS],
                }
            )
    return hits


# 00:00 UTC on the first day of the month after now
def _first_of_next_month(now: datetime) -> datetime:
    utc = now.astimezone(UTC)
    year, month = (utc.year + 1, 1) if utc.month == 12 else (utc.year, utc.month + 1)
    return datetime(year, month, 1, tzinfo=UTC)
