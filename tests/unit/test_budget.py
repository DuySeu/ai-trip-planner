from __future__ import annotations

from decimal import Decimal

import pytest

from domain.budget import CostLine, cost_lines, over_budget_vnd, total_cost_vnd
from tests.fixtures.builders import bangkok_plan, bangkok_request, dalat_plan, dalat_request


def test_cost_lines_group_by_category_and_currency_with_stay_shared_by_travelers():
    lines = cost_lines(bangkok_plan(), 2)
    assert lines == [
        CostLine("transport", "THB", Decimal(200)),
        CostLine("transport", "VND", Decimal(5100000)),
        CostLine("accommodation", "THB", Decimal(3600)),
        CostLine("food", "THB", Decimal(350 * 8)),
        CostLine("shopping", "THB", Decimal(350 * 2)),
        CostLine("service", "VND", Decimal(350000)),
        CostLine("sightseeing", "THB", Decimal(350 * 4)),
    ]


def test_total_cost_counts_chosen_accommodation_only_and_converts_local():
    # THB per person: 14 items x 350 + hotel 1800 x 4 nights x 1 room / 2 + rabbit card 200 = 8700
    # VND per person: flights 2,500,000 + 2,600,000 + insurance 350,000 = 5,450,000
    per_person = Decimal("8700") * Decimal("720.5") + Decimal(5450000)
    assert per_person == Decimal("11718350.0")
    assert total_cost_vnd(bangkok_plan(), 2) == Decimal(23436700)


def test_total_cost_of_a_domestic_plan_needs_no_rate():
    # per person: items 1,860,000 + hotel 1,000,000 x 3 nights x 2 rooms / 4 + bike 120,000
    assert total_cost_vnd(dalat_plan(), 4) == Decimal(13920000)


def test_chosen_transport_option_is_not_counted_twice():
    plan = dalat_plan()
    transport = [line for line in cost_lines(plan, 4) if line.category == "transport"]
    # two bus items of 300,000 plus the bike rental; the option list adds nothing
    assert transport == [CostLine("transport", "VND", Decimal(720000))]


def test_unchosen_accommodation_is_not_counted():
    plan = dalat_plan()
    swapped = plan.model_copy(
        update={
            "accommodation": tuple(
                a.model_copy(update={"chosen": False}) for a in plan.accommodation
            )
        }
    )
    assert total_cost_vnd(plan, 4) - total_cost_vnd(swapped, 4) == Decimal(6000000)


def test_over_budget_is_zero_when_within_budget_and_positive_when_over():
    plan = dalat_plan()
    assert over_budget_vnd(plan, dalat_request(budget_amount="5000000")) == Decimal(0)
    assert over_budget_vnd(plan, dalat_request(budget_amount="3480000")) == Decimal(0)
    assert over_budget_vnd(plan, dalat_request(budget_amount="3000000")) == Decimal(1920000)


def test_over_budget_reads_a_total_budget_without_multiplying():
    request = bangkok_request(budget_amount="20000000", budget_scope="total")
    assert over_budget_vnd(bangkok_plan(), request) == Decimal(3436700)


def test_a_third_currency_cannot_be_costed():
    plan = dalat_plan()
    bad = plan.days[0].items[0].model_copy(update={"price_currency": "USD"})
    day = plan.days[0].model_copy(update={"items": (bad, *plan.days[0].items[1:])})
    with pytest.raises(ValueError):
        total_cost_vnd(plan.model_copy(update={"days": (day, *plan.days[1:])}), 4)
