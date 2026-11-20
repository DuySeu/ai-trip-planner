from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from api.deps import AppDeps, build_limiters, require_quota
from api.main import create_app
from api.middleware import MAX_BODY_BYTES
from core.logger import ColorFormatter
from core.settings import Settings, load_settings
from db.call_sink import DbCallSink
from db.repositories import llm_calls, quota
from models.model_router import ModelRouter

ENV = {
    "DB_USER": "u",
    "DB_PASSWORD": "p",
    "DB_NAME": "n",
    "OPENROUTER_API_KEY": "k",
    "TAVILY_API_KEY": "k",
    "PLANNER_MODELS": "a/b:free",
    "CHAT_MODELS": "a/b:free",
    "CLASSIFIER_MODELS": "a/b:free",
    "DAILY_LLM_CEILING_NEW_TRIPS": "2",
    "DAILY_LLM_CEILING_CHAT": "4",
    "DAILY_TAVILY_CEILING": "100",
}


# App with injected services; the pool is whatever the test passes
def make_app(pool: ConnectionPool, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings(ENV)
    now = lambda: datetime.now(UTC)  # noqa: E731
    router = ModelRouter(
        provider_for=lambda model_id: cast(Any, None),
        models={},
        sink=DbCallSink(pool),
        daily_cap_pattern="x",
        reset_hour_utc=0,
        now=now,
    )
    deps = AppDeps(
        settings=settings,
        pool=pool,
        router=router,
        http=httpx.Client(),
        search=cast(Any, None),
        limiters=build_limiters(settings, now),
        now=now,
    )
    return create_app(settings, deps)


# A pool that is not open, so every connection attempt fails at once
@pytest.fixture
def dead_pool() -> ConnectionPool:
    return ConnectionPool("host=127.0.0.1 port=1 dbname=x", open=False)


# Call the ASGI app directly with a body split into chunks and headers set by hand
def asgi_post(app: FastAPI, path: str, chunks: list[bytes], headers: dict[str, str]) -> int:
    sent = list(chunks)
    status: list[int] = []

    async def receive() -> dict[str, Any]:
        body = sent.pop(0) if sent else b""
        return {"type": "http.request", "body": body, "more_body": bool(sent)}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    return status[0]


def test_unknown_error_returns_500_envelope_without_exception_text(dead_pool, caplog):
    app = make_app(dead_pool)

    # GET /boom - Fail with a message that must never reach the client
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret-db-password")

    caplog.handler.setFormatter(ColorFormatter(use_color=False))
    with caplog.at_level(logging.ERROR):
        response = TestClient(app, raise_server_exceptions=False).get(
            "/boom", headers={"X-Request-ID": "req-42"}
        )

    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "internal_error"
    assert "secret-db-password" not in response.text
    assert response.headers["X-Request-ID"] == "req-42"
    assert "request_id=req-42" in caplog.text
    assert "RuntimeError: secret-db-password" in caplog.text


def test_request_id_is_generated_when_missing_or_unsafe(dead_pool):
    client = TestClient(make_app(dead_pool))
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32
    forged = client.get("/health", headers={"X-Request-ID": "bad id\twith space"})
    assert forged.headers["X-Request-ID"] != "bad id\twith space"


def test_unknown_route_and_validation_errors_use_the_envelope(dead_pool):
    app = make_app(dead_pool)

    # GET /number - Needs an integer query parameter
    @app.get("/number")
    def number(n: int) -> None:
        return None

    client = TestClient(app)
    missing = client.get("/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    invalid = client.get("/number", params={"n": "abc-secret"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_request"
    assert "abc-secret" not in invalid.text


def test_body_over_64kb_is_rejected_with_413(dead_pool):
    app = make_app(dead_pool)

    # POST /echo - Read the whole body
    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    client = TestClient(app)
    over = client.post("/echo", content=b"x" * (MAX_BODY_BYTES + 1))
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "payload_too_large"
    assert client.post("/echo", content=b"x" * MAX_BODY_BYTES).json() == {"size": MAX_BODY_BYTES}


def test_body_cap_counts_streamed_bytes_when_content_length_lies_or_is_missing(dead_pool):
    app = make_app(dead_pool)

    # POST /echo - Read the whole body
    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    chunks = [b"x" * 40_000, b"x" * 40_000]
    assert asgi_post(app, "/echo", chunks, {"Content-Length": "10"}) == 413
    assert asgi_post(app, "/echo", chunks, {}) == 413
    assert asgi_post(app, "/echo", [b"x" * 10], {"Content-Length": "10"}) == 200


def test_ready_returns_503_when_db_unreachable(dead_pool):
    response = TestClient(make_app(dead_pool)).get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


def test_ready_returns_200_when_db_answers(db_pool):
    response = TestClient(make_app(db_pool)).get("/ready")
    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ready"}


# An app with one trip route and one chat route behind the quota gate
def quota_app(pool: ConnectionPool) -> TestClient:
    app = make_app(pool)

    # POST /trip - Gated as a new trip
    @app.post("/trip", dependencies=[Depends(require_quota("trip"))])
    def trip() -> dict[str, bool]:
        return {"ok": True}

    # POST /gated-chat - Gated as a chat message
    @app.post("/gated-chat", dependencies=[Depends(require_quota("chat"))])
    def chat() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_active_quota_block_returns_429_quota_exhausted(db_pool, db_conn):
    until = datetime.now(UTC) + timedelta(hours=2)
    quota.block(db_conn, "openrouter", until, "daily cap")
    client = quota_app(db_pool)
    for path in ("/trip", "/gated-chat"):
        response = client.post(path)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "quota_exhausted"
        assert until.isoformat() in response.json()["error"]["message"]


def test_expired_quota_block_lets_requests_through(db_pool, db_conn):
    quota.block(db_conn, "openrouter", datetime.now(UTC) - timedelta(minutes=1), "old")
    assert quota_app(db_pool).post("/trip").status_code == 200


def test_new_trip_ceiling_blocks_trips_but_not_chat(db_pool, db_conn):
    # The trip ceiling is 2 calls today and the chat ceiling 4
    for _ in range(2):
        llm_calls.log_call(db_conn, llm_calls.LlmCallRecord("generate", "a/b:free", "ok"))
    client = quota_app(db_pool)
    trip = client.post("/trip")
    assert trip.status_code == 429
    assert trip.json()["error"]["code"] == "quota_exhausted"
    assert client.post("/gated-chat").status_code == 200

    for _ in range(2):
        llm_calls.log_call(db_conn, llm_calls.LlmCallRecord("answer", "a/b:free", "ok"))
    assert client.post("/gated-chat").status_code == 429


def test_tavily_ceiling_blocks_trips_but_not_chat(db_pool, db_conn):
    settings = load_settings({**ENV, "DAILY_TAVILY_CEILING": "1"})
    for i in range(1):
        db_conn.execute(
            "INSERT INTO search_cache (key, provider, query, payload, expires_at) "
            "VALUES (%s, 'tavily', 'q', '{}', now() + interval '1 day')",
            (f"k{i}",),
        )
    app = make_app(db_pool, settings)

    # POST /trip - Gated as a new trip
    @app.post("/trip", dependencies=[Depends(require_quota("trip"))])
    def trip() -> dict[str, bool]:
        return {"ok": True}

    # POST /gated-chat - Gated as a chat message
    @app.post("/gated-chat", dependencies=[Depends(require_quota("chat"))])
    def chat() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/trip").status_code == 429
    assert client.post("/gated-chat").status_code == 200
