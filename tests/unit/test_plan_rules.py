from __future__ import annotations

from collections.abc import Callable

from domain.plan import Day, Plan, PlanItem, TransportOption
from domain.plan_rules import check_plan
from tests.fixtures.builders import (
    BANGKOK_SOURCE_IDS,
    DALAT_SOURCE_IDS,
    bangkok_plan,
    bangkok_request,
    dalat_plan,
    dalat_request,
)

PLAN = dalat_plan()
REQ = dalat_request()


# Errors of the Da Lat plan after a change
def errors_of(plan: Plan, request=REQ, sources=DALAT_SOURCE_IDS) -> list[str]:
    return check_plan(plan, request, sources).errors


# The plan with one day's items rewritten
def with_items(plan: Plan, index: int, change: Callable[[list[PlanItem]], list[PlanItem]]) -> Plan:
    days = list(plan.days)
    days[index] = days[index].model_copy(update={"items": tuple(change(list(days[index].items)))})
    return plan.model_copy(update={"days": tuple(days)})


# The plan with its transport options rewritten
def with_options(
    plan: Plan, change: Callable[[list[TransportOption]], list[TransportOption]]
) -> Plan:
    return plan.model_copy(
        update={"transport_options": tuple(change(list(plan.transport_options)))}
    )


def test_valid_fixtures_have_no_errors():
    assert errors_of(PLAN) == []
    assert check_plan(bangkok_plan(), bangkok_request(), BANGKOK_SOURCE_IDS).errors == []


def test_missing_trip_date_is_an_error():
    plan = PLAN.model_copy(update={"days": PLAN.days[:-1]})
    assert "days: missing 2026-12-23" in errors_of(plan)


def test_day_outside_the_trip_is_an_error():
    extra = Day(date=PLAN.days[-1].date.replace(day=24), items=())
    plan = PLAN.model_copy(update={"days": (*PLAN.days, extra)})
    assert "days: 2026-12-24 is outside the trip" in errors_of(plan)


def test_a_date_twice_is_an_error():
    plan = PLAN.model_copy(update={"days": (*PLAN.days, PLAN.days[1])})
    assert "days: 2026-12-21 appears twice" in errors_of(plan)


def test_items_out_of_time_order_is_an_error():
    plan = with_items(PLAN, 1, lambda items: items[::-1])
    assert "days: items on 2026-12-21 are not in start_time order" in errors_of(plan)


def test_item_ending_before_it_starts_is_an_error():
    plan = with_items(
        PLAN, 1, lambda items: [items[0].model_copy(update={"end_time": "07:00"}), *items[1:]]
    )
    assert any("ends before it starts" in e for e in errors_of(plan))


def test_items_without_times_do_not_break_the_order_rule():
    plan = with_items(
        PLAN,
        1,
        lambda items: [
            items[0].model_copy(update={"start_time": None, "end_time": None}),
            *items[1:],
        ],
    )
    assert errors_of(plan) == []


def test_third_currency_is_an_error():
    plan = with_items(
        PLAN, 1, lambda items: [items[0].model_copy(update={"price_currency": "USD"}), *items[1:]]
    )
    assert any("uses USD" in e for e in errors_of(plan))


def test_local_currency_is_an_error_on_a_domestic_trip():
    plan = with_items(
        PLAN, 1, lambda items: [items[0].model_copy(update={"price_currency": "THB"}), *items[1:]]
    )
    assert any("uses THB" in e for e in errors_of(plan))


def test_local_currency_is_allowed_abroad():
    assert check_plan(bangkok_plan(), bangkok_request(), BANGKOK_SOURCE_IDS).errors == []


def test_one_outbound_option_is_an_error():
    plan = with_options(PLAN, lambda opts: [o for o in opts if o.id != "tr_2"])
    assert "transport: the outbound leg needs 2 to 3 options, found 1" in errors_of(plan)


def test_four_return_options_is_an_error():
    extra = [
        PLAN.transport_options[3].model_copy(update={"id": f"tr_{n}", "chosen": False})
        for n in (8, 9)
    ]
    plan = with_options(PLAN, lambda opts: [*opts, *extra])
    assert "transport: the return leg needs 2 to 3 options, found 4" in errors_of(plan)


def test_two_chosen_outbound_options_is_an_error():
    plan = with_options(
        PLAN,
        lambda opts: [o.model_copy(update={"chosen": True}) if o.id == "tr_2" else o for o in opts],
    )
    assert "transport: the outbound leg needs 1 chosen option, found 2" in errors_of(plan)


def test_no_chosen_return_option_is_an_error():
    plan = with_options(
        PLAN,
        lambda opts: [
            o.model_copy(update={"chosen": False}) if o.id == "tr_3" else o for o in opts
        ],
    )
    assert "transport: the return leg needs 1 chosen option, found 0" in errors_of(plan)


def test_chosen_option_without_linked_item_is_an_error():
    plan = with_items(PLAN, 0, lambda items: items[1:])
    assert any(
        "chosen outbound option tr_1 has no transport item on the first day" in e
        for e in errors_of(plan)
    )
    plan = with_items(PLAN, 3, lambda items: items[:-1])
    assert any(
        "chosen return option tr_3 has no transport item on the last day" in e
        for e in errors_of(plan)
    )


def test_two_chosen_accommodations_is_an_error():
    plan = PLAN.model_copy(
        update={
            "accommodation": tuple(
                a.model_copy(update={"chosen": True}) for a in PLAN.accommodation
            )
        }
    )
    assert "accommodation: at most 1 chosen, found 2" in errors_of(plan)


def test_no_chosen_accommodation_is_allowed():
    plan = PLAN.model_copy(
        update={
            "accommodation": tuple(
                a.model_copy(update={"chosen": False}) for a in PLAN.accommodation
            )
        }
    )
    assert errors_of(plan) == []


def test_source_basis_without_source_id_is_an_error():
    plan = with_items(
        PLAN, 1, lambda items: [items[0].model_copy(update={"price_basis": "source"}), *items[1:]]
    )
    assert any("has price_basis source but no source_id" in e for e in errors_of(plan))


def test_unknown_source_id_is_removed_and_price_becomes_estimate():
    plan = with_items(
        PLAN,
        1,
        lambda items: [
            items[1].model_copy(update={"source_id": 99, "price_basis": "source"}),
            *items[1:],
        ],
    )
    result = check_plan(plan, REQ, DALAT_SOURCE_IDS)
    item = result.plan.days[1].items[0]
    assert (item.source_id, item.price_basis, result.errors) == (None, "estimate", [])
    assert plan.days[1].items[0].source_id == 99


def test_unknown_source_id_on_a_transport_option_is_cleaned_too():
    result = check_plan(PLAN, REQ, frozenset({2, 3}))
    options = {o.id: o for o in result.plan.transport_options}
    assert (options["tr_1"].source_id, options["tr_1"].price_basis) == (None, "estimate")
    assert result.errors == []


def test_empty_plan_reports_missing_days_without_crashing():
    plan = PLAN.model_copy(update={"days": ()})
    errors = errors_of(plan)
    assert "days: missing 2026-12-20" in errors and "days: missing 2026-12-23" in errors
