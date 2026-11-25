"""The visitor's current city and its weather, for the banner and the default origin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.deps import Deps
from api.envelope import ApiResponse, error_response
from api.schemas.weather import CurrentLocationOut, current_location_out
from core.exceptions import ResearchFailed
from domain.trip_request import Language
from research.current_location import current_location

router = APIRouter()


# GET /weather/current - The city at lat/lon and its weather now; nothing about it is stored
@router.get("/weather/current", response_model=ApiResponse[CurrentLocationOut])
def current_weather(
    deps: Deps,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    language: Language = "en",
) -> ApiResponse[CurrentLocationOut] | JSONResponse:
    try:
        found = current_location(deps.http, deps.location_cache, lat, lon, language)
    except ResearchFailed:
        return error_response(503, "unavailable", "Location is not available right now")
    return ApiResponse(success=True, data=current_location_out(found))
