"""Outside hosts of the backend: the API URLs it calls and the domains each web search may read."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

# Open-Meteo: place name to coordinates, forecast for the next days, and past days
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# ExchangeRate-API open endpoint: rates of one base currency, updated daily
RATES_URL = "https://open.er-api.com/v6/latest/{base}"

# The kinds of web search the backend runs. The first five are the research of a trip, "chat" is
# a question asked in a conversation, "discovery" is the search for places to go
SearchTask = Literal[
    "accommodation", "transport", "local_transport", "activities", "food", "chat", "discovery"
]

# Domains that may answer each task (Tavily include_domains). A task with an empty tuple searches
# the whole web. A search that finds nothing inside its list is run again without the list.
GUIDES = ("tripadvisor.com", "lonelyplanet.com", "wikivoyage.org")
SEARCH_DOMAINS: Mapping[SearchTask, tuple[str, ...]] = {
    "accommodation": (
        "booking.com",
        "agoda.com",
        "traveloka.com",
    ),
    "transport": (
        "rome2rio.com",
        "12go.asia",
        "skyscanner.com",
        "traveloka.com",
        "vexere.com",
        "dsvn.vn",
    ),
    "local_transport": ("rome2rio.com", *GUIDES),
    "activities": ("klook.com", "viator.com", "getyourguide.com", "vietnam.travel", *GUIDES),
    "food": ("foody.vn", "guide.michelin.com", *GUIDES),
    "chat": GUIDES,
    "discovery": ("vietnam.travel", *GUIDES),
}
