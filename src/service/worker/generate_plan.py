"""The generate_plan job: research, write the plan, save it, and settle failures."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import httpx
from psycopg_pool import ConnectionPool

from core.exceptions import (
    InvalidLLMOutput,
    LLMBudgetExceeded,
    LLMUnavailable,
    PlanConflict,
    QuotaExhausted,
    ResearchFailed,
)
from core.logger import log_context
from core.settings import Settings
from db.repositories import jobs, trips
from db.repositories.jobs import JobRow
from db.repositories.research import SourceInput, SourceRow, save_sources, sources_for_trip
from domain.plan import Plan
from domain.trip_request import TripRequest, today_in_vietnam
from models.model_router import CallBudget, CallContext, ModelRouter
from planning.plan_generator import generate_plan
from research.cache import DbCache
from research.exchange_rates import vnd_rate
from research.queries import ResearchKind
from research.research_service import ResearchDeps, run_research
from research.weather import weather_for_trip
from service.tavily.search import SearchHit, WebSearch

logger = logging.getLogger(__name__)

BACKOFF_BASE_S = 30
MAX_ERROR_CHARS = 300


# Everything a job needs: settings, the database, the LLM router and the research calls
@dataclass(frozen=True)
class JobDeps:
    settings: Settings
    pool: ConnectionPool
    router: ModelRouter
    research: ResearchDeps
    now: Callable[[], datetime]


# The research calls: the given web search, Open-Meteo and the exchange rate through the database cache
def build_research_deps(
    settings: Settings,
    pool: ConnectionPool,
    http: httpx.Client,
    search: WebSearch,
    now: Callable[[], datetime],
) -> ResearchDeps:
    cache = DbCache(pool)
    return ResearchDeps(
        search=search,
        weather=lambda lat, lon, start, end, today: weather_for_trip(
            http, cache, lat, lon, start, end, today
        ),
        rate=lambda currency, today: vnd_rate(http, cache, currency, today),
        save_sources=lambda trip_id, kind, hits: save_new_sources(pool, trip_id, kind, hits),
    )


# Save the hits the trip does not hold yet and return one row per hit, so a retried job
# adds no duplicate rows and the ids the plan cites stay valid
def save_new_sources(
    pool: ConnectionPool, trip_id: UUID, kind: ResearchKind, hits: Sequence[SearchHit]
) -> list[SourceRow]:
    with pool.connection() as conn:
        held = {(r.kind, r.url): r for r in sources_for_trip(conn, trip_id)}
        fresh = {h.url: h for h in hits if (kind, h.url) not in held}
        items = [SourceInput(h.title, h.url, h.content) for h in fresh.values()]
        held |= {
            (r.kind, r.url): r for r in save_sources(conn, trip_id=trip_id, kind=kind, items=items)
        }
    return [held[(kind, h.url)] for h in hits]


# Run one leased job to its end: succeeded, requeued for a retry, or failed
def run_generate_plan(job: JobRow, deps: JobDeps) -> None:
    budget = CallBudget(limit=deps.settings.llm_calls_per_job, used=job.llm_calls_used)
    with log_context(job_id=job.id, trip_id=job.trip_id):
        # A job leased more often than max_attempts lost its worker each time: stop it for good
        if job.attempts > job.max_attempts:
            logger.error("job abandoned after %s leases", job.attempts - 1)
            _give_up(job, deps, "generation_failed", "worker died on every attempt")
            return
        try:
            _generate(job, deps, budget)
        except QuotaExhausted as exc:
            logger.warning("job failed, quota exhausted: %s", exc)
            _give_up(job, deps, "quota_exhausted", str(exc))
        except LLMBudgetExceeded as exc:
            logger.warning("job failed, LLM budget used up: %s", exc)
            _give_up(job, deps, "llm_budget_exceeded", str(exc))
        except PlanConflict as exc:
            logger.warning("job dropped, the plan changed while it ran: %s", exc)
            _give_up(job, deps, "plan_conflict", str(exc))
        except (ResearchFailed, InvalidLLMOutput, LLMUnavailable) as exc:
            logger.warning("job attempt %s failed: %s", job.attempts, exc)
            _retry_or_give_up(job, deps, exc)
        finally:
            # Calls are written back even when the attempt failed, so the cap spans attempts
            with deps.pool.connection() as conn:
                jobs.add_llm_calls(conn, job.id, budget.used - job.llm_calls_used)


# The attempt: research, plan, save and finish the job in one transaction
def _generate(job: JobRow, deps: JobDeps, budget: CallBudget) -> None:
    with deps.pool.connection() as conn:
        trip = trips.get_trip(conn, job.trip_id)
        trips.set_status(conn, trip.id, "researching")
        jobs.set_stage(conn, job.id, "researching")

    request = TripRequest.model_validate(job.request or _request_dict(trip))
    previous = None if trip.plan is None else Plan.model_validate(trip.plan)
    today = today_in_vietnam(deps.now())
    research = run_research(request, trip.id, deps.research, today)

    with deps.pool.connection() as conn:
        trips.set_status(conn, trip.id, "planning")
        jobs.set_stage(conn, job.id, "planning")
    ctx = CallContext(trip_id=trip.id, budget=budget)
    generated = generate_plan(deps.router, request, research, previous, ctx)

    with deps.pool.connection() as conn:
        jobs.set_stage(conn, job.id, "validating")
        # The revision is read now: the plan this attempt replaces is the one stored at this moment
        current = trips.get_trip(conn, trip.id)
        trips.save_plan(
            conn,
            trip.id,
            current.plan_revision,
            generated.plan.model_dump(mode="json"),
            generated.total_cost_vnd,
            generated.over_budget,
            generated.model_id,
            request=job.request,
        )
        trips.set_status(conn, trip.id, "ready")
        jobs.finish(conn, job.id, "succeeded")
    logger.info("job succeeded, plan model %s", generated.model_id)


# A TripRequest dict from the trip's request columns
def _request_dict(trip: trips.TripRow) -> dict[str, object]:
    return {
        "destination": {
            "name": trip.destination_name,
            "country_code": trip.destination_country,
            "lat": trip.destination_lat,
            "lon": trip.destination_lon,
        },
        "origin": trip.origin,
        "start_date": trip.start_date,
        "end_date": trip.end_date,
        "travelers": trip.travelers,
        "travel_styles": trip.travel_styles,
        "budget_amount": trip.budget_amount,
        "budget_scope": trip.budget_scope,
        "language": trip.language,
        "notes": trip.notes,
    }


# End the job as failed, no retry; the trip fails, or stays ready when a plan already stands
def _give_up(job: JobRow, deps: JobDeps, reason: str, error: str) -> None:
    with deps.pool.connection() as conn:
        trip = trips.get_trip(conn, job.trip_id)
        trips.set_status(conn, trip.id, "failed" if trip.plan is None else "ready", reason)
        jobs.finish(conn, job.id, "failed", error[:MAX_ERROR_CHARS])


# Run the job again after 30 s x 2^(attempts-1) while attempts remain, else fail it
def _retry_or_give_up(job: JobRow, deps: JobDeps, exc: Exception) -> None:
    if job.attempts >= job.max_attempts:
        _give_up(job, deps, "generation_failed", str(exc))
        return
    run_after = deps.now() + timedelta(seconds=BACKOFF_BASE_S * 2 ** (job.attempts - 1))
    with deps.pool.connection() as conn:
        trips.set_status(conn, job.trip_id, "queued")
        jobs.requeue(conn, job.id, run_after, str(exc)[:MAX_ERROR_CHARS])
