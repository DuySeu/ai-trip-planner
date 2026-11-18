"""Rules a plan must meet before it is saved, checked in code and not by the model."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import timedelta
from typing import TypeVar

from domain.currency import HOME_CURRENCY
from domain.plan import Accommodation, Plan, PlanItem, TransportOption
from domain.trip_request import TripRequest

T = TypeVar("T", PlanItem, TransportOption, Accommodation)


# The sanitized plan and the broken rules, as short sentences for the model to repair
@dataclass(frozen=True)
class RuleResult:
    plan: Plan
    errors: list[str]


# Check a plan against the request and the research set; unknown sources are cleaned, not errors
def check_plan(plan: Plan, request: TripRequest, known_source_ids: AbstractSet[int]) -> RuleResult:
    errors: list[str] = []

    # A source the research does not hold is dropped and its price becomes an estimate
    def clean(entry: T) -> T:
        if entry.source_id is not None and entry.source_id not in known_source_ids:
            return entry.model_copy(update={"source_id": None, "price_basis": "estimate"})
        return entry

    days = tuple(
        day.model_copy(update={"items": tuple(clean(i) for i in day.items)}) for day in plan.days
    )
    plan = plan.model_copy(
        update={
            "days": days,
            "transport_options": tuple(clean(o) for o in plan.transport_options),
            "accommodation": tuple(clean(a) for a in plan.accommodation),
        }
    )

    errors += _check_days(plan, request)
    errors += _check_currencies(plan)
    errors += _check_transport(plan, request)
    errors += _check_accommodation(plan)
    errors += _check_sources(plan)
    return RuleResult(plan, errors)


# One day per trip date, items inside the trip and in time order
def _check_days(plan: Plan, request: TripRequest) -> list[str]:
    errors: list[str] = []
    span = (request.end_date - request.start_date).days + 1
    wanted = [request.start_date + timedelta(days=n) for n in range(span)]
    have = [day.date for day in plan.days]
    errors += [f"days: missing {d.isoformat()}" for d in wanted if d not in have]
    errors += [
        f"days: {d.isoformat()} is outside the trip" for d in dict.fromkeys(have) if d not in wanted
    ]
    errors += [
        f"days: {d.isoformat()} appears twice" for d in dict.fromkeys(have) if have.count(d) > 1
    ]

    for day in plan.days:
        label = day.date.isoformat()
        times = [i.start_time for i in day.items if i.start_time is not None]
        if times != sorted(times):
            errors.append(f"days: items on {label} are not in start_time order")
        for item in day.items:
            if item.start_time and item.end_time and item.start_time > item.end_time:
                errors.append(f"items: {item.title!r} on {label} ends before it starts")
    return errors


# Every price is in VND or the trip's local currency
def _check_currencies(plan: Plan) -> list[str]:
    allowed = {HOME_CURRENCY, plan.currencies.local}
    priced: list[tuple[str, str]] = [
        (f"item {i.title!r}", i.price_currency) for d in plan.days for i in d.items
    ]
    priced += [
        (f"transport option {o.summary!r}", o.price_currency) for o in plan.transport_options
    ]
    priced += [(f"accommodation {a.name!r}", a.price_currency) for a in plan.accommodation]
    priced += [(f"checklist {c.label!r}", c.price_currency) for c in plan.checklist]
    return [
        f"currency: {what} uses {currency}, allowed are {sorted(c for c in allowed if c)}"
        for what, currency in priced
        if currency not in allowed
    ]


# Two or three options per leg with one chosen, in the requested modes, linked to items
def _check_transport(plan: Plan, request: TripRequest) -> list[str]:
    errors: list[str] = []
    by_date = {day.date: day for day in plan.days}
    legs = (("outbound", request.start_date, "first"), ("return", request.end_date, "last"))
    for leg, date_, where in legs:
        options = [o for o in plan.transport_options if o.leg == leg]
        chosen = [o for o in options if o.chosen]
        if not 2 <= len(options) <= 3:
            errors.append(f"transport: the {leg} leg needs 2 to 3 options, found {len(options)}")
        if len(chosen) != 1:
            errors.append(f"transport: the {leg} leg needs 1 chosen option, found {len(chosen)}")
        day = by_date.get(date_)
        for option in chosen:
            name = option.id or repr(option.summary)
            # An option without an id yet cannot be linked, so it is checked after assign_ids
            if option.id and day and not any(i.option_id == option.id for i in day.items):
                errors.append(
                    f"transport: chosen {leg} option {name} has no transport item on the "
                    f"{where} day ({date_.isoformat()})"
                )
    return errors


# At most one stay is chosen
def _check_accommodation(plan: Plan) -> list[str]:
    chosen = sum(1 for a in plan.accommodation if a.chosen)
    return [f"accommodation: at most 1 chosen, found {chosen}"] if chosen > 1 else []


# A price marked as from a source must name the source
def _check_sources(plan: Plan) -> list[str]:
    errors = [
        f"sources: item {i.title!r} on {d.date.isoformat()} has price_basis source but no source_id"
        for d in plan.days
        for i in d.items
        if i.price_basis == "source" and i.source_id is None
    ]
    errors += [
        f"sources: transport option {o.summary!r} has price_basis source but no source_id"
        for o in plan.transport_options
        if o.price_basis == "source" and o.source_id is None
    ]
    errors += [
        f"sources: accommodation {a.name!r} has price_basis source but no source_id"
        for a in plan.accommodation
        if a.price_basis == "source" and a.source_id is None
    ]
    return errors
