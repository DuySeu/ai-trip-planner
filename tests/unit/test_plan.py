from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from domain.plan import (
    CATEGORY_LABELS_VI,
    Accommodation,
    ChecklistItem,
    Day,
    Plan,
    PlanItem,
    TransportOption,
    assign_ids,
    next_id,
    transport_item,
)
from tests.fixtures.builders import bangkok_plan, dalat_plan

CURRENCIES = {"home": "VND", "local": None, "local_to_home_rate": None, "rate_date": None}


# A one-day plan whose items, options, stays and checklist entries are given
def make_plan(
    items: tuple[PlanItem, ...] = (),
    options: tuple[TransportOption, ...] = (),
    stays: tuple[Accommodation, ...] = (),
    checklist: tuple[ChecklistItem, ...] = (),
) -> Plan:
    return Plan(
        title="t",
        currencies=CURRENCIES,  # type: ignore[arg-type]
        days=(Day(date=date(2026, 12, 20), items=items),),
        transport_options=options,
        accommodation=stays,
        checklist=checklist,
    )


def test_plan_fixture_round_trips_through_json():
    for plan in (bangkok_plan(), dalat_plan()):
        assert Plan.model_validate_json(plan.model_dump_json()) == plan
        assert Plan.model_validate(plan.model_dump(mode="json")) == plan


def test_money_is_a_json_number_and_loads_back_as_decimal():
    plan = bangkok_plan()
    dumped = plan.model_dump(mode="json")
    assert dumped["days"][0]["items"][1]["price_per_person"] == 350
    assert dumped["currencies"]["rate_date"] == "2026-11-16"
    assert plan.days[0].items[1].price_per_person == Decimal(350)
    item = PlanItem(title="x", category="food", price_per_person=Decimal("12.5"))
    assert json.loads(item.model_dump_json())["price_per_person"] == 12.5


def test_json_schema_can_be_built_for_a_prompt():
    schema = Plan.model_json_schema()
    assert {"title", "currencies", "days"} <= set(schema["properties"])
    assert "PlanItem" in schema["$defs"]


def test_plan_is_frozen():
    with pytest.raises(ValidationError):
        bangkok_plan().title = "other"  # type: ignore[misc]


def test_item_rejects_bad_time_unknown_category_and_negative_price():
    with pytest.raises(ValidationError):
        PlanItem(title="x", category="food", start_time="8:00")
    with pytest.raises(ValidationError):
        PlanItem.model_validate({"title": "x", "category": "fun"})
    with pytest.raises(ValidationError):
        PlanItem(title="x", category="food", price_per_person=Decimal(-1))


def test_accommodation_rejects_check_out_not_after_check_in():
    with pytest.raises(ValidationError):
        Accommodation(
            name="h",
            check_in=date(2026, 12, 20),
            check_out=date(2026, 12, 20),
            price_per_night=Decimal(1),
        )


def test_assign_ids_keeps_existing_ids_and_fills_empty_ones():
    plan = make_plan(
        items=(
            PlanItem(id="it_7", title="a", category="food"),
            PlanItem(title="b", category="food"),
            PlanItem(title="c", category="food"),
        ),
        options=(TransportOption(leg="local", mode="car", summary="s"),),
        stays=(
            Accommodation(
                name="h",
                check_in=date(2026, 12, 20),
                check_out=date(2026, 12, 21),
                price_per_night=Decimal(1),
            ),
        ),
        checklist=(ChecklistItem(id="ck_2", label="a"), ChecklistItem(label="b")),
    )
    filled = assign_ids(plan)
    assert [i.id for i in filled.days[0].items] == ["it_7", "it_8", "it_9"]
    assert [o.id for o in filled.transport_options] == ["tr_1"]
    assert [a.id for a in filled.accommodation] == ["ac_1"]
    assert [c.id for c in filled.checklist] == ["ck_2", "ck_3"]
    assert plan.days[0].items[1].id == ""
    assert assign_ids(filled) == filled


def test_next_id_is_one_above_the_highest_number():
    assert next_id(bangkok_plan(), "it") == "it_18"
    assert next_id(make_plan(), "tr") == "tr_1"


def test_transport_item_copies_price_and_links_option():
    option = TransportOption(
        id="tr_9",
        leg="outbound",
        mode="train",
        summary="SE1",
        depart="2026-12-20T19:00",
        duration_minutes=90,
        price_per_person=Decimal(900000),
        price_basis="source",
        source_id=3,
    )
    item = transport_item(option, date(2026, 12, 20))
    assert (item.category, item.option_id, item.transport_mode) == ("transport", "tr_9", "train")
    assert (item.price_per_person, item.price_basis, item.source_id) == (
        Decimal(900000),
        "source",
        3,
    )
    assert (item.start_time, item.end_time) == ("19:00", "20:30")


def test_transport_item_has_no_times_on_another_day_or_when_it_crosses_midnight():
    option = TransportOption(
        id="tr_9",
        leg="outbound",
        mode="train",
        summary="SE1",
        depart="2026-12-20T19:00",
        duration_minutes=960,
    )
    assert transport_item(option, date(2026, 12, 21)).start_time is None
    crossing = transport_item(option, date(2026, 12, 20))
    assert (crossing.start_time, crossing.end_time) == ("19:00", None)


def test_category_labels_cover_every_category_in_template_order():
    assert list(CATEGORY_LABELS_VI.values()) == [
        "Đi lại",
        "Lưu trú",
        "Ăn uống",
        "Mua sắm",
        "Dịch vụ",
        "Thăm quan",
    ]
