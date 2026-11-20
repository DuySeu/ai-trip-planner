from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from domain.hotels import MAX_HOTEL_CARDS, HotelCard, hotel_cards_out


def hotel(name: str, source_id: int, price: str | None = None) -> HotelCard:
    return HotelCard(
        name=name,
        area="Ngô Quyền",
        stars=4,
        price_per_night=Decimal(price) if price else None,
        highlights=("Pool",),
        source_id=source_id,
    )


def test_hotel_cards_out_drops_unknown_sources_and_adds_url():
    cards = (hotel("Mercure", 1, "1500000"), hotel("Made up", 99))
    out = hotel_cards_out(cards, {1: "https://www.booking.com/hotel/vn/mercure.html"})
    assert [c["name"] for c in out] == ["Mercure"]
    assert out[0]["url"] == "https://www.booking.com/hotel/vn/mercure.html"
    assert out[0]["price_per_night"] == 1500000.0
    assert out[0]["source_id"] == 1


def test_hotel_cards_out_puts_priced_cards_first_and_keeps_six():
    cards = tuple(hotel(f"H{i}", 1, "900000" if i % 2 else None) for i in range(8))
    out = hotel_cards_out(cards, {1: "https://www.agoda.com/x"})
    assert len(out) == MAX_HOTEL_CARDS == 6
    assert [c["name"] for c in out[:4]] == ["H1", "H3", "H5", "H7"]
    assert all(c["price_per_night"] is None for c in out[4:])


def test_hotel_card_rejects_six_stars():
    with pytest.raises(ValidationError):
        HotelCard(name="Palace", stars=6, source_id=1)
