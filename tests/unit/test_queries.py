from __future__ import annotations

from research.queries import build_queries
from tests.fixtures.builders import bangkok_request, dalat_request

KINDS = {"accommodation", "transport", "local_transport", "activities", "food"}


def test_build_queries_returns_five_kinds_in_vietnamese_for_vn():
    queries = build_queries(dalat_request())

    assert set(queries) == KINDS
    assert all("Đà Lạt" in q for q in queries.values())
    assert "khách sạn" in queries["accommodation"]
    assert "Ho Chi Minh City" in queries["transport"]


def test_build_queries_uses_english_abroad():
    queries = build_queries(bangkok_request())

    assert set(queries) == KINDS
    assert all("Bangkok" in q for q in queries.values())
    assert "hotels" in queries["accommodation"]
    assert not any("khách sạn" in q for q in queries.values())


def test_build_queries_transport_names_origin_and_destination():
    queries = build_queries(bangkok_request())

    assert "Ho Chi Minh City" in queries["transport"] and "Bangkok" in queries["transport"]


def test_build_queries_names_the_travel_styles_in_activities():
    queries = build_queries(bangkok_request(travel_styles=["culture", "nightlife"]))

    assert "culture" in queries["activities"] and "nightlife" in queries["activities"]
