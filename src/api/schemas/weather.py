"""Response body of the visitor's current city and weather."""

from __future__ import annotations

from pydantic import BaseModel

from research.current_location import CurrentLocation


# The weather now, as Open-Meteo reports it
class CurrentWeatherOut(BaseModel):
    temperature_c: float
    weather_code: int
    summary: str


# The visitor's city; weather is null when the forecast could not be read
class CurrentLocationOut(BaseModel):
    city: str
    country_code: str
    weather: CurrentWeatherOut | None


# The public view of a current location
def current_location_out(found: CurrentLocation) -> CurrentLocationOut:
    weather = found.weather
    return CurrentLocationOut(
        city=found.city,
        country_code=found.country_code,
        weather=None
        if weather is None
        else CurrentWeatherOut(
            temperature_c=weather.temperature_c,
            weather_code=weather.weather_code,
            summary=weather.summary,
        ),
    )
