from __future__ import annotations

from decimal import Decimal

from domain.flights import MAX_FLIGHT_CARDS, FlightCard, flight_cards_out


def card(carrier: str, source_id: int, price: str | None = None) -> FlightCard:
    return FlightCard(
        carrier=carrier,
        route="Hà Nội - Đà Nẵng",
        price_from=Decimal(price) if price else None,
        source_id=source_id,
    )


def test_flight_cards_with_unknown_sources_are_dropped_and_priced_first():
    cards = (card("Vietjet", 1), card("Made up", 99, "1"), card("Vietnam Airlines", 2, "1500000"))
    out = flight_cards_out(cards, {1: "https://a.example/1", 2: "https://a.example/2"})
    assert [c["carrier"] for c in out] == ["Vietnam Airlines", "Vietjet"]
    assert out[0]["price_from"] == 1500000.0
    assert out[0]["url"] == "https://a.example/2"
    assert out[1]["price_from"] is None
    assert out[0]["mode"] == "flight"


def test_flight_cards_are_capped():
    cards = tuple(card(f"C{n}", 1) for n in range(MAX_FLIGHT_CARDS + 2))
    assert len(flight_cards_out(cards, {1: "https://a.example"})) == MAX_FLIGHT_CARDS
