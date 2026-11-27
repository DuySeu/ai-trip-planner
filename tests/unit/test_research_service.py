from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from core.exceptions import QuotaExhausted, ResearchFailed
from db.repositories.research import SourceRow
from domain.plan import Weather
from research.queries import ResearchKind, build_queries
from research.research_service import ResearchBundle, ResearchDeps, run_research
from service.tavily.search import SearchHit
from tests.fakes import FakeSearch
from tests.fixtures.builders import bangkok_request, dalat_request

TODAY = date(2026, 11, 17)
TRIP_ID = uuid4()
HIT = SearchHit("Title", "https://example.com/a", "text")
SUNNY = Weather(summary="Clear sky", temp_min_c=15, temp_max_c=24, precip_mm=0, basis="forecast")


# Fakes for the weather, the rate and the repository, recording what they were asked
class Calls:
    def __init__(self, rate: tuple[Decimal, date] | Exception | None = None) -> None:
        self.rate_result = rate if rate is not None else (Decimal("720.5"), date(2026, 11, 17))
        self.rates: list[str] = []
        self.weather: list[tuple[float, float, date, date, date]] = []
        self.saved: list[tuple[UUID, str, Sequence[SearchHit]]] = []

    def get_weather(
        self, lat: float, lon: float, start: date, end: date, today: date
    ) -> dict[date, Weather]:
        self.weather.append((lat, lon, start, end, today))
        return {start: SUNNY}

    def get_rate(self, currency: str, today: date) -> tuple[Decimal, date]:
        self.rates.append(currency)
        if isinstance(self.rate_result, Exception):
            raise self.rate_result
        return self.rate_result

    def save(self, trip_id: UUID, kind: ResearchKind, hits: Sequence[SearchHit]) -> list[SourceRow]:
        self.saved.append((trip_id, kind, hits))
        return [
            SourceRow(
                id=len(self.saved) * 10 + i,
                trip_id=trip_id,
                conversation_id=None,
                kind=kind,
                cache_key=None,
                title=h.title,
                url=h.url,
                snippet=h.content,
                created_at=datetime(2026, 11, 17, tzinfo=UTC),
            )
            for i, h in enumerate(hits)
        ]


def deps_for(search: FakeSearch, calls: Calls) -> ResearchDeps:
    return ResearchDeps(
        search=search, weather=calls.get_weather, rate=calls.get_rate, save_sources=calls.save
    )


def test_domestic_trip_skips_rate_and_has_no_local_currency():
    calls, search = Calls(), FakeSearch(default=[HIT])

    bundle = run_research(dalat_request(), TRIP_ID, deps_for(search, calls), TODAY)

    assert calls.rates == []
    assert bundle.currencies.local is None and bundle.currencies.local_to_home_rate is None
    assert bundle.failed_kinds == ()
    assert len(search.calls) == 5


def test_each_search_gets_its_research_kind_as_task():
    search = FakeSearch(default=[HIT])

    run_research(dalat_request(), TRIP_ID, deps_for(search, Calls()), TODAY)

    assert sorted(search.tasks) == sorted(build_queries(dalat_request()))


def test_each_search_gets_the_destination_country():
    search = FakeSearch(default=[HIT])

    run_research(bangkok_request(), TRIP_ID, deps_for(search, Calls()), TODAY)

    assert search.countries == ["TH"] * 5


def test_trip_abroad_gets_local_currency_rate_and_date():
    calls, search = Calls(), FakeSearch(default=[HIT])

    bundle = run_research(bangkok_request(), TRIP_ID, deps_for(search, calls), TODAY)

    assert calls.rates == ["THB"]
    assert bundle.currencies.local == "THB"
    assert bundle.currencies.local_to_home_rate == Decimal("720.5")
    assert bundle.currencies.rate_date == date(2026, 11, 17)


def test_weather_is_asked_for_the_destination_and_trip_dates():
    calls = Calls()

    bundle = run_research(
        dalat_request(), TRIP_ID, deps_for(FakeSearch(default=[HIT]), calls), TODAY
    )

    assert calls.weather == [(11.9404, 108.4583, date(2026, 12, 20), date(2026, 12, 23), TODAY)]
    assert bundle.weather == {date(2026, 12, 20): SUNNY}


def test_sources_are_saved_per_kind_and_returned():
    calls = Calls()
    request = dalat_request()
    queries = build_queries(request)
    search = FakeSearch(
        {queries["food"]: [HIT, SearchHit("B", "https://example.com/b", "t")]}, [HIT]
    )

    bundle = run_research(request, TRIP_ID, deps_for(search, calls), TODAY)

    assert {(trip, kind) for trip, kind, _ in calls.saved} == {(TRIP_ID, k) for k in queries}
    assert len(bundle.sources) == 6
    assert {s.kind for s in bundle.sources} == set(queries)


def test_partial_search_failure_is_reported_not_raised():
    calls = Calls()
    request = dalat_request()
    queries = build_queries(request)
    search = FakeSearch({queries["food"]: ResearchFailed("down")}, [HIT])

    bundle = run_research(request, TRIP_ID, deps_for(search, calls), TODAY)

    assert bundle.failed_kinds == ("food",)
    assert "food" not in {kind for _, kind, _ in calls.saved}
    assert len(bundle.sources) == 4


def test_all_searches_failing_raises_research_failed():
    search = FakeSearch(
        {q: ResearchFailed("down") for q in build_queries(dalat_request()).values()}
    )

    with pytest.raises(ResearchFailed):
        run_research(dalat_request(), TRIP_ID, deps_for(search, Calls()), TODAY)


def test_missing_rate_abroad_raises_research_failed():
    calls = Calls(rate=ResearchFailed("no rate"))

    with pytest.raises(ResearchFailed):
        run_research(bangkok_request(), TRIP_ID, deps_for(FakeSearch(default=[HIT]), calls), TODAY)


def test_quota_exhausted_during_search_propagates():
    request = dalat_request()
    queries = build_queries(request)
    until = datetime(2026, 12, 1, tzinfo=UTC)
    search = FakeSearch({queries["activities"]: QuotaExhausted(until)}, [HIT])

    with pytest.raises(QuotaExhausted):
        run_research(request, TRIP_ID, deps_for(search, Calls()), TODAY)


def test_a_search_with_no_results_is_not_a_failure():
    bundle = run_research(
        dalat_request(), TRIP_ID, deps_for(FakeSearch(default=[]), Calls()), TODAY
    )

    assert bundle == ResearchBundle(
        currencies=bundle.currencies, weather=bundle.weather, sources=(), failed_kinds=()
    )
