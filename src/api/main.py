"""FastAPI application factory.

Run (from the repo root), after the .env is filled:

    PYTHONPATH=src uvicorn api.main:app_factory --factory --reload

Then open http://127.0.0.1:8000/docs for the interactive API.
"""

from __future__ import annotations

import functools
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import AppDeps, build_limiters, limit_api
from api.errors import register_error_handlers
from api.middleware import REQUEST_ID_HEADER, BodyLimitMiddleware, RequestIdMiddleware
from api.routes import chat, exports, health, places, trips, users
from core.logger import configure_logging
from core.settings import Settings, load_settings
from core.wiring import build_router
from db.pool import open_pool
from service.tavily.search import build_web_search

HTTP_TIMEOUT_S = 10.0

# Routers behind the per-IP API limit; later tasks add theirs here
API_ROUTERS: tuple[APIRouter, ...] = (
    users.router,
    places.router,
    trips.router,
    exports.router,
    chat.router,
)


# Mount every router; health stays outside the per-IP limit so probes are never refused
def include_routers(app: FastAPI) -> None:
    app.include_router(health.router, tags=["health"])
    for router in API_ROUTERS:
        app.include_router(router, dependencies=[Depends(limit_api)])


# Build the real services from settings; the caller closes them with close_deps
def build_deps(settings: Settings) -> AppDeps:
    now: Callable[[], datetime] = functools.partial(datetime.now, UTC)
    pool = open_pool(settings.db.conninfo())

    router = build_router(settings, pool, now)
    return AppDeps(
        settings=settings,
        pool=pool,
        router=router,
        http=httpx.Client(timeout=HTTP_TIMEOUT_S),
        search=build_web_search(settings, pool, now),
        limiters=build_limiters(settings, now),
        now=now,
    )


# Create the app; with no deps it builds the real ones and closes them on shutdown
def create_app(settings: Settings, deps: AppDeps | None = None) -> FastAPI:
    owned = deps is None
    app_deps = deps if deps is not None else build_deps(settings)

    # Close only what this function built
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if owned:
            app_deps.http.close()
            app_deps.pool.close()

    app = FastAPI(title="ai-trip-planner API", lifespan=lifespan)
    app.state.deps = app_deps

    # Last added runs first: CORS wraps the request id, which wraps the body cap
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition"],
    )
    register_error_handlers(app)
    include_routers(app)
    return app


# Factory for uvicorn: settings from the environment, JSON logs on
def app_factory() -> FastAPI:
    settings = load_settings(os.environ)
    configure_logging("INFO")
    return create_app(settings)
