"""Dashboard routes: system health now and usage over the last days. Open to every caller, so they
return counts and grouped labels only (see db.repositories.stats)."""

from __future__ import annotations

from enum import IntEnum

from fastapi import APIRouter

from api.deps import Conn, Deps
from api.envelope import ApiResponse
from db.repositories import stats

router = APIRouter()


# The ranges GET /stats/usage accepts; an IntEnum so the query string "7" parses (a Literal does not)
class UsageDays(IntEnum):
    WEEK = 7
    MONTH = 30
    QUARTER = 90


# GET /stats/health - LLM use against today's ceilings, errors, job queue, provider blocks
@router.get("/stats/health")
def get_health(deps: Deps, conn: Conn) -> ApiResponse[stats.HealthStats]:
    settings = deps.settings
    data = stats.health(conn, settings.daily_llm_ceiling_new_trips, settings.daily_llm_ceiling_chat)
    return ApiResponse(success=True, data=data)


# GET /stats/usage - Users, trips and chat over the last 7, 30 or 90 Vietnam days
@router.get("/stats/usage")
def get_usage(conn: Conn, days: UsageDays = UsageDays.MONTH) -> ApiResponse[stats.UsageStats]:
    return ApiResponse(success=True, data=stats.usage(conn, int(days)))
