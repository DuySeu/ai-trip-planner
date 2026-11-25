"""Shared services built once at startup, and the FastAPI dependencies that use them."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal

import httpx
from fastapi import Depends, Request
from psycopg import Connection
from psycopg_pool import ConnectionPool

from api.limits import RateLimiter, client_ip
from core.exceptions import QuotaExhausted
from core.settings import Settings
from db.repositories import llm_calls, quota

if TYPE_CHECKING:
    from models.model_router import ModelRouter
    from service.tavily.search import WebSearch

TAVILY = "tavily"
HTTP_TIMEOUT_S = 10.0
READY_TIMEOUT_S = 2.0


# Per-IP limiters, one per kind of request
@dataclass(frozen=True)
class Limiters:
    api: RateLimiter
    trip_create: RateLimiter
    chat: RateLimiter


# Everything routes share, built once in create_app
@dataclass(frozen=True)
class AppDeps:
    settings: Settings
    pool: ConnectionPool
    router: ModelRouter
    http: httpx.Client
    search: WebSearch
    limiters: Limiters
    now: Callable[[], datetime]


# The limiters for the configured per-IP numbers; a kind with no daily cap gets a day's worth
def build_limiters(settings: Settings, now: Callable[[], datetime]) -> Limiters:
    minutes_per_day = 24 * 60
    return Limiters(
        api=RateLimiter(
            settings.ip_requests_per_minute, settings.ip_requests_per_minute * minutes_per_day, now
        ),
        trip_create=RateLimiter(settings.ip_trips_per_day, settings.ip_trips_per_day, now),
        chat=RateLimiter(settings.ip_chat_per_minute, settings.ip_chat_per_day, now),
    )


# The services shared by every request
def get_deps(request: Request) -> AppDeps:
    deps: AppDeps = request.app.state.deps
    return deps


Deps = Annotated[AppDeps, Depends(get_deps)]


# One pooled connection per request, committed when the request ends and rolled back on error
def get_conn(deps: Deps) -> Iterator[Connection[Any]]:
    with deps.pool.connection() as conn:
        yield conn


Conn = Annotated[Connection[Any], Depends(get_conn)]


# Count a request against the caller's IP bucket for general API use
def limit_api(request: Request, deps: Deps) -> None:
    deps.limiters.api.hit(client_ip(request, deps.settings.trust_proxy_headers))


# Count a new trip against the caller's IP daily cap
def limit_trip_create(request: Request, deps: Deps) -> None:
    deps.limiters.trip_create.hit(client_ip(request, deps.settings.trust_proxy_headers))


# Count a chat message against the caller's IP caps
def limit_chat(request: Request, deps: Deps) -> None:
    deps.limiters.chat.hit(client_ip(request, deps.settings.trust_proxy_headers))


# A dependency that refuses work while a provider is blocked or today's global ceiling is reached
def require_quota(kind: Literal["trip", "chat"]) -> Callable[..., None]:
    # Check provider blocks first, then the global daily ceiling for this kind
    def check(deps: Deps, conn: Conn) -> None:
        llm = deps.router.service
        services = (llm, TAVILY) if kind == "trip" else (llm,)
        for service in services:
            until = quota.active_block(conn, service)
            if until is not None:
                raise QuotaExhausted(until)

        settings = deps.settings
        ceiling = (
            settings.daily_llm_ceiling_new_trips
            if kind == "trip"
            else settings.daily_llm_ceiling_chat
        )
        exhausted = llm_calls.count_today(conn) >= ceiling
        if kind == "trip":
            exhausted = exhausted or quota.count_tavily_today(conn) >= settings.daily_tavily_ceiling
        if exhausted:
            # The counts cover the UTC day, so they reset at the next 00:00 UTC
            midnight = deps.now().replace(hour=0, minute=0, second=0, microsecond=0)
            raise QuotaExhausted(midnight + timedelta(days=1))

    return check
