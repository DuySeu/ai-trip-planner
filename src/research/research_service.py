"""All research for one trip, run in parallel: web searches, weather and the exchange rate."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from core.exceptions import ResearchFailed
from db.repositories.research import SourceRow
from domain.currency import Currencies, local_currency_for
from domain.plan import Weather
from domain.trip_request import TripRequest
from research.queries import ResearchKind, build_queries
from service.tavily.search import SearchHit, WebSearch

logger = logging.getLogger(__name__)

# Five searches, weather and the rate all start at once
MAX_WORKERS = 7


# What research found; sources are the saved rows the plan cites by id
@dataclass(frozen=True)
class ResearchBundle:
    currencies: Currencies
    weather: Mapping[date, Weather]
    sources: tuple[SourceRow, ...]
    failed_kinds: tuple[ResearchKind, ...]


# The calls research makes, as plain callables so tests need no network or database
@dataclass(frozen=True)
class ResearchDeps:
    search: WebSearch
    weather: Callable[[float, float, date, date, date], dict[date, Weather]]
    rate: Callable[[str, date], tuple[Decimal, date]]
    save_sources: Callable[[UUID, ResearchKind, Sequence[SearchHit]], list[SourceRow]]


# Research the trip: five searches, weather and (abroad) the exchange rate, in parallel.
# A failed search is listed in failed_kinds; QuotaExhausted, no search at all, or no rate abroad
# stop the research. Sources are saved after the parallel part, in the calling thread.
def run_research(
    request: TripRequest, trip_id: UUID, deps: ResearchDeps, today: date
) -> ResearchBundle:
    queries = build_queries(request)
    local = local_currency_for(request.destination.country_code)
    dest = request.destination

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        searches = {
            kind: pool.submit(deps.search, query, kind, dest.country_code)
            for kind, query in queries.items()
        }
        weather = pool.submit(
            deps.weather, dest.lat, dest.lon, request.start_date, request.end_date, today
        )
        rate = pool.submit(deps.rate, local, today) if local else None

        # Collect the searches; a failure drops only that kind
        found: dict[ResearchKind, list[SearchHit]] = {}
        failed: list[ResearchKind] = []
        for kind, future in searches.items():
            try:
                found[kind] = future.result()
            except ResearchFailed as exc:
                logger.warning("research %s failed: %s", kind, exc)
                failed.append(kind)
        if not found:
            raise ResearchFailed("every web search failed")

        currencies = Currencies()
        if rate is not None:
            rate_value, rate_date = rate.result()
            currencies = Currencies(local=local, local_to_home_rate=rate_value, rate_date=rate_date)
        days = weather.result()

    sources = [
        row for kind, hits in found.items() for row in deps.save_sources(trip_id, kind, hits)
    ]
    return ResearchBundle(currencies, days, tuple(sources), tuple(failed))
