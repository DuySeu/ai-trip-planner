"""Web search for the whole project: one Tavily client, cached 24 h, with the quota block."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from psycopg_pool import ConnectionPool

from core.exceptions import QuotaExhausted, ResearchFailed
from core.settings import Settings
from db.call_sink import DbCallSink
from domain.trip_request import language_of
from models.model_router import CallSink
from research.cache import Cache, DbCache, cache_key
from service.tavily.client import TavilyClient, create_client
from utils.domain import (
    COUNTRY_TASKS,
    FRESH_TASKS,
    PRICE_MAX_AGE_HOURS,
    SEARCH_DOMAINS,
    TAVILY_COUNTRY,
    SearchTask,
)

SERVICE = "tavily"
PROVIDER = "tavily"
CACHE_TTL = timedelta(hours=24)
SEARCH_MAX_RESULTS = 5
MAX_SNIPPET_CHARS = 500
MAX_ERROR_CHARS = 300
# Tavily refuses live fetching under load with 434; the search then runs on its cached copies
FLEX_CAPACITY = re.compile(r"\b434\b|flex tier capacity", re.IGNORECASE)


# One search result as the planner sees it; content is cut to MAX_SNIPPET_CHARS
@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    content: str


# One query, the task it is for and the destination's country (ISO 3166-1 alpha-2, when known)
# in, hits out: the call any part of the backend makes to search the web. The task picks the
# domains the search prefers.
class WebSearch(Protocol):
    def __call__(
        self, query: str, task: SearchTask, country_code: str | None = None
    ) -> list[SearchHit]: ...


# The web search with the real client, the database cache and the quota block behind it
def build_web_search(
    settings: Settings, pool: ConnectionPool, now: Callable[[], datetime]
) -> WebSearch:
    client = create_client(settings.tavily_api_key)
    cache = DbCache(pool)
    sink = DbCallSink(pool)

    def search(query: str, task: SearchTask, country_code: str | None = None) -> list[SearchHit]:
        return tavily_search(
            client,
            cache,
            sink,
            query,
            SEARCH_MAX_RESULTS,
            settings.tavily_quota_pattern,
            now(),
            SEARCH_DOMAINS.get(task, ()),
            search_options(query, task, country_code),
        )

    return search


# Tavily options of one search: the language of the query, the destination's country for a task
# that reads local pages, and fresh cached copies for a task that reads prices
def search_options(query: str, task: SearchTask, country_code: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {"language": language_of(query)}
    country = TAVILY_COUNTRY.get(country_code or "")
    if country and task in COUNTRY_TASKS:
        options["country"] = country
    if task in FRESH_TASKS:
        options["max_age_hours"] = PRICE_MAX_AGE_HOURS
    return options


# Results for query, cached 24 h per query and options. A quota error blocks the service until the
# first day of next month (Tavily's free credits are monthly) and raises QuotaExhausted; other
# errors raise ResearchFailed. A cached query is served even while the service is blocked.
# include_domains are preferred, not required: the rest of the web may still answer.
def tavily_search(
    client: TavilyClient,
    cache: Cache,
    sink: CallSink,
    query: str,
    max_results: int,
    quota_pattern: str,
    now: datetime,
    include_domains: Sequence[str] = (),
    options: Mapping[str, Any] | None = None,
) -> list[SearchHit]:
    params: dict[str, Any] = {"max_results": max_results, **(options or {})}
    if include_domains:
        params["include_domains"] = sorted(include_domains)
        params["include_domains_mode"] = "prefer"
    key = cache_key(PROVIDER, query, params)
    payload = cache.get(key)
    if payload is None:
        # Refuse while blocked, then call Tavily
        until = sink.blocked_until(SERVICE)
        if until is not None and until > now:
            raise QuotaExhausted(until)
        payload = _fetch(client, sink, query, params, quota_pattern, now)
        cache.put(key, PROVIDER, query, payload, CACHE_TTL)
    return [SearchHit(h["title"], h["url"], h["content"]) for h in payload["hits"]]


# One Tavily call, made once more without max_age_hours when live fetching is refused (434); the
# third-party client raises its own error types, so any failure is mapped here
def _fetch(
    client: TavilyClient,
    sink: CallSink,
    query: str,
    params: Mapping[str, Any],
    quota_pattern: str,
    now: datetime,
) -> dict[str, Any]:
    try:
        try:
            response = client.search(query, **params)
        except Exception as exc:
            if "max_age_hours" not in params or not FLEX_CAPACITY.search(str(exc)):
                raise
            cached_only = {k: v for k, v in params.items() if k != "max_age_hours"}
            response = client.search(query, **cached_only)
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
