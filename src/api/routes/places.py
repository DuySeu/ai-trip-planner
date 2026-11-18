"""Destination search for the trip form."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import StringConstraints

from api.deps import Deps
from api.envelope import ApiResponse, error_response
from api.schemas.places import PlaceOut, place_out
from core.exceptions import ResearchFailed
from domain.trip_request import Language
from research.cache import DbCache
from research.places import search_places

router = APIRouter()

SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


# GET /places - Search destinations by name (2 to 100 characters, up to 10 results)
@router.get("/places", response_model=ApiResponse[list[PlaceOut]])
def places(
    deps: Deps, q: Annotated[SearchText, Query()], language: Language = "en"
) -> ApiResponse[list[PlaceOut]] | JSONResponse:
    try:
        found = search_places(deps.http, DbCache(deps.pool), q, language)
    except ResearchFailed:
        return error_response(503, "unavailable", "Place search is not available right now")
    return ApiResponse(success=True, data=[place_out(place) for place in found])
