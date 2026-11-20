"""Hotel options for a chat question about where to stay and what it costs.

The model writes the cards from search results; code keeps the cards whose source is known and
sets each card's url from that source."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.plan import CurrencyCode

MAX_HOTEL_CARDS = 6


# Base of every hotel model: immutable
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# One hotel as a search result shows it; a price the result does not state stays empty
class HotelCard(_Frozen):
    name: str = Field(min_length=1)
    area: str = ""
    stars: int | None = Field(default=None, ge=1, le=5)
    price_per_night: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    price_currency: CurrencyCode = "VND"
    highlights: tuple[str, ...] = Field(default=(), max_length=3)
    source_id: int


# The model's answer: a short reply and the hotel cards
class HotelOptionsReply(_Frozen):
    reply: str = Field(min_length=1)
    cards: tuple[HotelCard, ...] = ()


# The cards to show, as JSON with their source url: unknown sources dropped, priced cards first
def hotel_cards_out(
    cards: tuple[HotelCard, ...], sources: Mapping[int, str]
) -> list[dict[str, Any]]:
    known = [c for c in cards if c.source_id in sources]
    ordered = sorted(known, key=lambda c: c.price_per_night is None)[:MAX_HOTEL_CARDS]
    return [
        {
            **c.model_dump(mode="json"),
            "price_per_night": None if c.price_per_night is None else float(c.price_per_night),
            "url": sources[c.source_id],
        }
        for c in ordered
    ]
