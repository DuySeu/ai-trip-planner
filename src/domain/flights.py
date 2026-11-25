"""Flight, train or bus options for a chat question about getting somewhere and what it costs.

The model writes the cards from search results; code keeps the cards whose source is known and
sets each card's url from that source."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.plan import CurrencyCode
from domain.trip_request import TransportMode

MAX_FLIGHT_CARDS = 6


# Base of every flight model: immutable
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# One option as a search result shows it; a price the result does not state stays empty
class FlightCard(_Frozen):
    carrier: str = Field(min_length=1)
    mode: TransportMode = "flight"
    route: str = Field(min_length=1)
    duration_text: str = ""
    price_from: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    price_currency: CurrencyCode = "VND"
    highlights: tuple[str, ...] = Field(default=(), max_length=3)
    source_id: int


# The model's answer: a short reply, the cards, and the origin the visitor named in the message
# (None when the message names none; code still checks the message before trusting it)
class FlightOptionsReply(_Frozen):
    reply: str = Field(min_length=1)
    cards: tuple[FlightCard, ...] = ()
    origin: str | None = Field(default=None, max_length=200)


# The cards to show, as JSON with their source url: unknown sources dropped, priced cards first
def flight_cards_out(
    cards: tuple[FlightCard, ...], sources: Mapping[int, str]
) -> list[dict[str, Any]]:
    known = [c for c in cards if c.source_id in sources]
    ordered = sorted(known, key=lambda c: c.price_from is None)[:MAX_FLIGHT_CARDS]
    return [
        {
            **c.model_dump(mode="json"),
            "price_from": None if c.price_from is None else float(c.price_from),
            "url": sources[c.source_id],
        }
        for c in ordered
    ]
