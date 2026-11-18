"""Write a trip plan from the request and the research, then check it in code."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from core.exceptions import InvalidLLMOutput, LLMUnavailable
from core.prompts import budget_cut_prompt, planner_prompt
from domain.budget import over_budget_vnd, total_cost_vnd
from domain.currency import Currencies
from domain.plan import (
    Plan,
    PlanItem,
    PlanWarning,
    TransportOption,
    assign_ids,
    transport_item,
)
from domain.plan_rules import check_plan
from domain.trip_request import TripRequest, budget_total_vnd
from models.model_router import CallContext, ModelRouter, call_json, compact_schema
from planning.plan_editor import LANGUAGE_NAMES, compact_plan
from research.research_service import ResearchBundle

logger = logging.getLogger(__name__)

# Fields set by code that the model must not see in the schema
HIDDEN_FIELDS = {
    "Plan": {"currencies", "warnings"},
    "Day": {"weather"},
    "PlanItem": {"id", "option_id"},
    "TransportOption": {"id"},
    "Accommodation": {"id"},
    "ChecklistItem": {"id"},
}


# What the model writes: a plan without the parts that code sets from research
class DraftPlan(Plan):
    currencies: Currencies = Currencies()


# The checked plan with the model that wrote it, its cost and whether it is over the budget
@dataclass(frozen=True)
class GeneratedPlan:
    plan: Plan
    model_id: str
    total_cost_vnd: Decimal
    over_budget: bool


# A whole number of VND for a message
def _vnd(amount: Decimal) -> str:
    return f"{amount:,.0f}"


# Source text as data: angle brackets are replaced so it cannot close or open a tag
def _data(text: str | None) -> str:
    return (text or "").replace("<", "(").replace(">", ")").strip()


# The user message: request, money rules, weather, numbered sources and the earlier plan
def _prompt_content(request: TripRequest, research: ResearchBundle, previous: Plan | None) -> str:
    local = research.currencies.local
    if local:
        currency = (
            f"Prices are in VND or {local}. 1 {local} = {research.currencies.local_to_home_rate} "
            f"VND on {research.currencies.rate_date}. Flights from Vietnam are usually quoted "
            f"in VND, things at the destination in {local}."
        )
    else:
        currency = "The trip is inside Vietnam. Every price is in VND."
    trip = (
        f"destination: {request.destination.name} ({request.destination.country_code})\n"
        f"origin: {request.origin}\n"
        f"dates: {request.start_date.isoformat()} to {request.end_date.isoformat()}\n"
        f"travelers: {request.travelers}\n"
        f"travel styles: {', '.join(request.travel_styles)}\n"
        f"budget: {_vnd(budget_total_vnd(request))} VND for the whole group, "
        f"{request.budget_scope.replace('_', ' ')} amount {_vnd(request.budget_amount)} VND"
    )
    if request.notes:
        trip += f"\nnotes from the visitor: {_data(request.notes)}"
    weather = "\n".join(
        f"{day.isoformat()}: {w.summary}, {w.temp_min_c:g} to {w.temp_max_c:g} C, "
        f"rain {w.precip_mm:g} mm ({w.basis})"
        for day, w in sorted(research.weather.items())
    )
    sources = "\n".join(
        f'<source id="{s.id}" kind="{s.kind}" title="{_data(s.title)}" url="{_data(s.url)}">'
        f"{_data(s.snippet)}</source>"
        for s in research.sources
    )
    parts = [
        f"<trip>\n{trip}\n</trip>",
        f"<currency>\n{currency}\n</currency>",
        f"<weather>\n{weather or 'none'}\n</weather>",
        f"<sources>\n{sources or 'none'}\n</sources>",
    ]
    if previous is not None:
        parts.append(f"<previous_plan>\n{_data(compact_plan(previous))}\n</previous_plan>")
    return "\n\n".join(parts)


# Put an item among a day's items by start time; one without a time goes first or last
def _place(items: tuple[PlanItem, ...], item: PlanItem, first: bool) -> tuple[PlanItem, ...]:
    if item.start_time is None:
        return (item, *items) if first else (*items, item)
    for pos, other in enumerate(items):
        if other.start_time is not None and other.start_time > item.start_time:
            return (*items[:pos], item, *items[pos:])
    return (*items, item)


# The model's draft as a full plan: ids, currencies and weather set by code, linked transport items added
def _assemble(draft: DraftPlan, request: TripRequest, research: ResearchBundle) -> Plan:
    days = tuple(
        day.model_copy(
            update={
                "weather": research.weather.get(day.date),
                "items": tuple(
                    i.model_copy(update={"id": "", "option_id": None}) for i in day.items
                ),
            }
        )
        for day in draft.days
    )
    plan = Plan(**dict(draft)).model_copy(
        update={
            "currencies": research.currencies,
            "days": days,
            "transport_options": tuple(
                o.model_copy(update={"id": ""}) for o in draft.transport_options
            ),
            "accommodation": tuple(a.model_copy(update={"id": ""}) for a in draft.accommodation),
            "checklist": tuple(c.model_copy(update={"id": ""}) for c in draft.checklist),
            "warnings": (),
        }
    )
    plan = assign_ids(plan)

    # Every leg with exactly one chosen option gets that option's item; others are rule errors
    days_list = list(plan.days)
    for leg, when in (("outbound", request.start_date), ("return", request.end_date)):
        chosen: list[TransportOption] = [
            o for o in plan.transport_options if o.leg == leg and o.chosen
        ]
        index = next((n for n, d in enumerate(days_list) if d.date == when), None)
        if len(chosen) == 1 and index is not None:
            items = _place(
                days_list[index].items, transport_item(chosen[0], when), leg == "outbound"
            )
            days_list[index] = days_list[index].model_copy(update={"items": items})
    return assign_ids(plan.model_copy(update={"days": tuple(days_list)}))


# A warning for every research kind that returned nothing
def _missing_research(research: ResearchBundle) -> tuple[PlanWarning, ...]:
    return tuple(
        PlanWarning(
            code="missing_research",
            message=f"No web research was found for {kind}; its prices and names are estimates.",
        )
        for kind in research.failed_kinds
    )


# Plan the trip: one call, plus one to cut the cost when the plan is over the budget
def generate_plan(
    router: ModelRouter,
    request: TripRequest,
    research: ResearchBundle,
    previous: Plan | None,
    ctx: CallContext,
) -> GeneratedPlan:
    known_ids = frozenset(s.id for s in research.sources)
    system = planner_prompt.format(
        language=LANGUAGE_NAMES[request.language],
        schema=compact_schema(DraftPlan, HIDDEN_FIELDS),
    )
    first_message = {"role": "user", "content": _prompt_content(request, research, previous)}

    # The rule errors of the assembled plan, so the model sees them as it would see the final plan
    def check(draft: DraftPlan) -> list[str]:
        return check_plan(_assemble(draft, request, research), request, known_ids).errors

    result = call_json(router, "generate", system, [first_message], DraftPlan, check, ctx)
    plan = check_plan(_assemble(result.value, request, research), request, known_ids).plan
    model_id = result.model_id

    over = over_budget_vnd(plan, request)
    if over > 0:
        total = total_cost_vnd(plan, request.travelers)
        cut_message = budget_cut_prompt.format(
            total=_vnd(total),
            travelers=request.travelers,
            budget=_vnd(budget_total_vnd(request)),
            over=_vnd(over),
        )
        messages = [
            first_message,
            {"role": "assistant", "content": result.value.model_dump_json(exclude_defaults=True)},
            {"role": "user", "content": cut_message},
        ]
        try:
            cut = call_json(router, "generate", system, messages, DraftPlan, check, ctx)
        except (InvalidLLMOutput, LLMUnavailable) as exc:
            logger.warning("budget cut failed, keeping the first plan: %s", exc)
        else:
            plan = check_plan(_assemble(cut.value, request, research), request, known_ids).plan
            model_id = cut.model_id
            over = over_budget_vnd(plan, request)

    warnings = _missing_research(research)
    if over > 0:
        warnings += (
            PlanWarning(
                code="over_budget",
                message=f"The plan is {_vnd(over)} VND over the budget of "
                f"{_vnd(budget_total_vnd(request))} VND.",
            ),
        )
    plan = plan.model_copy(update={"warnings": warnings})
    return GeneratedPlan(plan, model_id, total_cost_vnd(plan, request.travelers), over > 0)
