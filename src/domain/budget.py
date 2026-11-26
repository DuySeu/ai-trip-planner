"""What a plan costs, per person and in VND, and how far it is over the budget."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from domain.currency import to_vnd
from domain.plan import CATEGORY_LABELS_VI, Category, Plan
from domain.trip_request import TripRequest, budget_total_vnd


# One category's cost per person in one currency
@dataclass(frozen=True)
class CostLine:
    category: Category
    currency: str
    per_person: Decimal


# Non-zero costs per person by category and currency: items, the chosen stay, priced checklist
def cost_lines(plan: Plan, travelers: int) -> list[CostLine]:
    sums: dict[tuple[Category, str], Decimal] = defaultdict(Decimal)

    # Itinerary items already include the chosen transport options
    for day in plan.days:
        for item in day.items:
            sums[(item.category, item.price_currency)] += item.price_per_person

    # The stay is a price per room per night, shared by the group
    for stay in plan.accommodation:
        if stay.chosen:
            nights = (stay.check_out - stay.check_in).days
            total = stay.price_per_night * nights * stay.rooms
            sums[("accommodation", stay.price_currency)] += total / travelers

    for entry in plan.checklist:
        sums[(entry.category, entry.price_currency)] += entry.price_per_person

    order = list(CATEGORY_LABELS_VI)
    keys = sorted(sums, key=lambda k: (order.index(k[0]), k[1]))
    return [CostLine(c, cur, sums[(c, cur)]) for c, cur in keys if sums[(c, cur)] != 0]


# The whole group's cost in VND with the plan's stored rate, to the cent
def total_cost_vnd(plan: Plan, travelers: int) -> Decimal:
    lines = cost_lines(plan, travelers)
    per_person = sum((to_vnd(x.per_person, x.currency, plan.currencies) for x in lines), Decimal(0))
    return round(per_person * travelers, 2)


# How many VND the plan is over the request's budget; 0 when within it or when there is no budget
def over_budget_vnd(plan: Plan, request: TripRequest) -> Decimal:
    budget = budget_total_vnd(request)
    if budget is None:
        return Decimal(0)
    excess = total_cost_vnd(plan, request.travelers) - budget
    return max(excess, Decimal(0))
