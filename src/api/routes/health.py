"""Liveness and readiness endpoints."""

from __future__ import annotations

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.deps import READY_TIMEOUT_S, Deps
from api.envelope import ApiResponse, error_response

router = APIRouter()


# GET /health - Liveness: the process is up
@router.get("/health")
def health() -> ApiResponse[dict[str, str]]:
    return ApiResponse(success=True, data={"status": "ok"})


# GET /ready - Readiness: the database answers
@router.get("/ready", response_model=ApiResponse[dict[str, str]])
def ready(deps: Deps) -> ApiResponse[dict[str, str]] | JSONResponse:
    try:
        with deps.pool.connection(timeout=READY_TIMEOUT_S) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        return error_response(503, "unavailable", "The database is not reachable")
    return ApiResponse(success=True, data={"status": "ready"})
