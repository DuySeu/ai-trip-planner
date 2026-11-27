"""Turn one chat message into a validated edit of the trip plan."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from core.prompts import plan_editor_prompt
from db.repositories.messages import MessageRow
from domain.plan import Plan, PlanItem
from domain.plan_edit import EditRejected, PlanEdit, apply_edit
from domain.plan_rules import check_plan
from domain.trip_request import TripRequest
from models.model_router import CallContext, JsonResult, ModelRouter, call_json, compact_schema
from orchestration.state_manager import message_for_model

HISTORY_MESSAGES = 10
# Fields set by code that the model must not see in the schema
HIDDEN_FIELDS = {"PlanItem": {"option_id"}, "TransportOption": {"id"}, "Accommodation": {"id"}}
LANGUAGE_NAMES = {"en": "English", "vi": "Vietnamese"}


# An amount without trailing zeros, such as 350 or 12.5
def _amount(value: Decimal) -> str:
    return format(value.normalize(), "f")


# One line for a priced thing: "350 THB source#7" or "0 VND estimate"
def _price(amount: Decimal, currency: str, basis: str, source_id: int | None) -> str:
    cited = f"source#{source_id}" if basis == "source" and source_id is not None else basis
    return f"{_amount(amount)} {currency} {cited}"


# One line for an itinerary item
def _item_line(item: PlanItem) -> str:
    times = f"{item.start_time or '--:--'}-{item.end_time or '--:--'}"
    where = f" @ {item.location}" if item.location else ""
    link = f" [option {item.option_id}]" if item.option_id else ""
    price = _price(item.price_per_person, item.price_currency, item.price_basis, item.source_id)
    return (
        f"  {item.id} {times} [{item.category}] {item.title}{where} | {price} | {item.status}{link}"
    )


# The plan as text, one line per item, option, stay and checklist entry, each with its id
def compact_plan(plan: Plan) -> str:
    local = plan.currencies.local
    rate = plan.currencies.local_to_home_rate
    lines = [f"title: {plan.title}"]
    lines.append(
        f"currencies: VND, local {local} (1 {local} = {rate} VND)" if local else "currencies: VND"
    )
    for day in plan.days:
        lines.append(f"day {day.date.isoformat()}: {day.theme}")
        lines += [_item_line(item) for item in day.items]
    lines.append("transport options:")
    for o in plan.transport_options:
        price = _price(o.price_per_person, o.price_currency, o.price_basis, o.source_id)
        mark = " chosen" if o.chosen else ""
        lines.append(f"  {o.id} {o.leg} {o.mode}{mark}: {o.summary} | depart {o.depart} | {price}")
    lines.append("accommodation:")
    for a in plan.accommodation:
        price = _price(a.price_per_night, a.price_currency, a.price_basis, a.source_id)
        mark = " chosen" if a.chosen else ""
        lines.append(
            f"  {a.id}{mark}: {a.name} ({a.area}) {a.check_in.isoformat()} to "
            f"{a.check_out.isoformat()} | {price} per night x {a.rooms} rooms"
        )
    lines.append("checklist:")
    for c in plan.checklist:
        box = "x" if c.done else " "
        price = f"{_amount(c.price_per_person)} {c.price_currency}"
        lines.append(f"  {c.id} [{box}] {c.label} ({c.category}, {price})")
    return "\n".join(lines)


# The budget as the visitor gave it; none when the planner suggested it
def _budget(request: TripRequest) -> str:
    if request.budget_amount is None:
        return "none given"
    return f"{_amount(request.budget_amount)} VND {request.budget_scope}"


# The trip request as short lines for the prompt
def _request_text(request: TripRequest) -> str:
    return (
        f"destination: {request.destination.name} ({request.destination.country_code})\n"
        f"origin: {request.origin}\n"
        f"dates: {request.start_date.isoformat()} to {request.end_date.isoformat()}\n"
        f"travelers: {request.travelers}\n"
        f"styles: {', '.join(request.travel_styles)}\n"
        f"budget: {_budget(request)}\n"
        f"language: {request.language}"
    )


# Ask for an edit; it is applied to a copy and rule-checked, and a bad one gets one repair round
def propose_edit(
    router: ModelRouter,
    request: TripRequest,
    plan: Plan,
    history: Sequence[MessageRow],
    message: str,
    ctx: CallContext,
) -> JsonResult[PlanEdit]:
    system = plan_editor_prompt.format(
        language=LANGUAGE_NAMES[request.language],
        schema=compact_schema(PlanEdit, HIDDEN_FIELDS),
    )
    turns = "\n".join(f"{m.role}: {message_for_model(m)}" for m in history[-HISTORY_MESSAGES:])
    parts = [
        f"<trip>\n{_request_text(request)}\n</trip>",
        f"<plan>\n{compact_plan(plan)}\n</plan>",
        f"<conversation>\n{turns}\n</conversation>" if turns else "",
        f"<request>\n{message}\n</request>",
    ]
    content = "\n\n".join(p for p in parts if p)

    # Edit errors, or the rule errors of the edited plan; a re-plan request is not checked here
    def check(edit: PlanEdit) -> list[str]:
        try:
            result = apply_edit(plan, edit, request)
        except EditRejected as rejected:
            return rejected.errors
        if result.request_changes is not None:
            return []
        # Source ids are cleaned by check_plan, not errors, so an empty set is enough here
        return check_plan(result.plan, request, frozenset()).errors

    return call_json(
        router,
        "edit",
        system,
        [{"role": "user", "content": content}],
        PlanEdit,
        check,
        ctx,
        HIDDEN_FIELDS,
    )
