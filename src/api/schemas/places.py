"""Response body of the destination search."""

from __future__ import annotations

from pydantic import BaseModel

from research.places import Place


# One destination to pick in the trip form
class PlaceOut(BaseModel):
    name: str
    admin1: str | None
    country_code: str
    lat: float
    lon: float


# The public view of a search hit
def place_out(place: Place) -> PlaceOut:
    return PlaceOut(
        name=place.name,
        admin1=place.admin1,
        country_code=place.country_code,
        lat=place.lat,
        lon=place.lon,
    )
