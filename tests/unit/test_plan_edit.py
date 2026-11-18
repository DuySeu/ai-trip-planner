from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from domain.plan import Accommodation, ChecklistItem, Plan, PlanItem, TransportOption
from domain.plan_edit import (
    AddItem,
    AddTransportOption,
    ChooseTransportOption,
    EditRejected,
    ItemChanges,
    MoveItem,
    PlanEdit,
    RemoveItem,
    ReplaceDay,
    RequestChanges,
    SetAccommodation,
    UpdateChecklist,
    UpdateItem,
    UpdateRequest,
    apply_edit,
)
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


# An edit of the given operations
def edit(*ops: Any) -> PlanEdit:
    return PlanEdit(ops=ops, explanation="x")


# All items of a plan in order
def all_items(plan: Plan) -> list[PlanItem]:
    return [i for d in plan.days for i in d.items]


# One item by id
def item_of(plan: Plan, item_id: str) -> PlanItem:
    return next(i for i in all_items(plan) if i.id == item_id)


# One option by id
def option_of(plan: Plan, option_id: str) -> TransportOption:
    return next(o for o in plan.transport_options if o.id == option_id)


# A new flight option for a leg
def flight(leg: str = "outbound", price: int = 1200000) -> TransportOption:
    return TransportOption.model_validate(
        {
            "leg": leg,
            "mode": "flight",
            "summary": "Bamboo SGN - DLI",
            "depart": "2026-12-20T09:00",
            "duration_minutes": 55,
            "price_per_person": price,
        }
    )


def test_remove_item_leaves_every_other_item_unchanged():
    result = apply_edit(PLAN, edit(RemoveItem(op="remove_item", item_id="it_8")), REQ)
    before = [i for i in all_items(PLAN) if i.id != "it_8"]
    assert all_items(result.plan) == before
    assert result.changed == ["Removed it_8 Nhà thờ Con Gà và Dinh Bảo Đại"]


def test_unknown_item_id_is_rejected():
    with pytest.raises(EditRejected) as raised:
        apply_edit(PLAN, edit(RemoveItem(op="remove_item", item_id="it_99")), REQ)
    assert raised.value.errors == ["remove_item: unknown item id it_99"]


def test_every_problem_in_an_edit_is_reported_and_the_input_is_untouched():
    ops = (
        RemoveItem(op="remove_item", item_id="it_98"),
        UpdateItem(op="update_item", item_id="it_99", changes=ItemChanges(title="x")),
    )
    with pytest.raises(EditRejected) as raised:
        apply_edit(PLAN, edit(*ops), REQ)
    assert len(raised.value.errors) == 2


def test_update_item_changes_only_the_given_fields():
    changes = ItemChanges(price_per_person=Decimal(90000), note="book ahead")
    result = apply_edit(
        PLAN, edit(UpdateItem(op="update_item", item_id="it_6", changes=changes)), REQ
    )
    new, old = item_of(result.plan, "it_6"), item_of(PLAN, "it_6")
    assert (new.price_per_person, new.note) == (Decimal(90000), "book ahead")
    assert (
        new.model_copy(update={"price_per_person": old.price_per_person, "note": old.note}) == old
    )


def test_update_item_cannot_set_a_malformed_time():
    with pytest.raises(ValidationError):
        ItemChanges(start_time="9am")


def test_add_item_goes_in_time_order_with_a_fresh_id():
    new = PlanItem(title="Cà phê Tùng", category="food", start_time="10:00", end_time="11:00")
    result = apply_edit(PLAN, edit(AddItem(op="add_item", date=date(2026, 12, 21), item=new)), REQ)
    items = result.plan.days[1].items
    assert [i.id for i in items] == ["it_5", "it_6", "it_17", "it_7", "it_8", "it_9"]
    assert result.changed == ["Added it_17 Cà phê Tùng on 2026-12-21"]


def test_new_items_get_fresh_ids_that_do_not_collide():
    spoof = PlanItem(id="it_1", title="Spoof", category="food", option_id="tr_1")
    ops = (
        AddItem(op="add_item", date=date(2026, 12, 21), item=spoof),
        AddItem(op="add_item", date=date(2026, 12, 22), item=spoof),
    )
    result = apply_edit(PLAN, edit(*ops), REQ)
    ids = [i.id for i in all_items(result.plan)]
    assert len(ids) == len(set(ids)) == len(all_items(PLAN)) + 2
    assert item_of(result.plan, "it_17").option_id is None
    assert item_of(result.plan, "it_1") == item_of(PLAN, "it_1")


def test_add_item_outside_the_trip_is_rejected():
    new = PlanItem(title="x", category="food")
    with pytest.raises(EditRejected) as raised:
        apply_edit(PLAN, edit(AddItem(op="add_item", date=date(2026, 12, 30), item=new)), REQ)
    assert "outside the trip" in raised.value.errors[0]


def test_move_item_to_another_day_keeps_its_id_and_orders_by_time():
    op = MoveItem(
        op="move_item",
        item_id="it_13",
        date=date(2026, 12, 21),
        start_time="10:00",
        end_time="11:00",
    )
    result = apply_edit(PLAN, edit(op), REQ)
    assert [i.id for i in result.plan.days[1].items] == [
        "it_5",
        "it_6",
        "it_13",
        "it_7",
        "it_8",
        "it_9",
    ]
    assert "it_13" not in [i.id for i in result.plan.days[2].items]
    assert item_of(result.plan, "it_13").start_time == "10:00"


def test_move_item_without_times_keeps_its_times():
    op = MoveItem(op="move_item", item_id="it_9", date=date(2026, 12, 22))
    result = apply_edit(PLAN, edit(op), REQ)
    assert item_of(result.plan, "it_9").start_time == "19:00"
    assert [i.id for i in result.plan.days[2].items][-1] == "it_9"


def test_choose_transport_option_swaps_linked_item_and_flags():
    result = apply_edit(
        PLAN, edit(ChooseTransportOption(op="choose_transport_option", option_id="tr_2")), REQ
    )
    assert [(o.id, o.chosen) for o in result.plan.transport_options if o.leg == "outbound"] == [
        ("tr_1", False),
        ("tr_2", True),
    ]
    linked = result.plan.days[0].items[0]
    assert (linked.id, linked.option_id, linked.transport_mode) == ("it_1", "tr_2", "flight")
    assert (linked.price_per_person, linked.price_basis) == (Decimal(1500000), "estimate")
    assert [i.id for i in result.plan.days[0].items] == ["it_1", "it_2", "it_3", "it_4"]
    assert result.changed == ["Chose tr_2 for outbound"]
    assert check_plan(result.plan, REQ, DALAT_SOURCE_IDS).errors == []


def test_choose_transport_option_leaves_the_other_leg_alone():
    result = apply_edit(
        PLAN, edit(ChooseTransportOption(op="choose_transport_option", option_id="tr_4")), REQ
    )
    assert result.plan.days[0] == PLAN.days[0]
    assert result.plan.days[3].items[-1].option_id == "tr_4"
    assert option_of(result.plan, "tr_3").chosen is False


def test_choosing_an_unknown_option_is_rejected():
    with pytest.raises(EditRejected):
        apply_edit(
            PLAN, edit(ChooseTransportOption(op="choose_transport_option", option_id="tr_77")), REQ
        )


def test_add_transport_option_with_choose_true_becomes_the_chosen_one():
    result = apply_edit(
        PLAN, edit(AddTransportOption(op="add_transport_option", option=flight(), choose=True)), REQ
    )
    assert option_of(result.plan, "tr_6").chosen is True
    assert option_of(result.plan, "tr_1").chosen is False
    linked = [i for i in all_items(result.plan) if i.option_id]
    assert sorted(i.option_id or "" for i in linked) == ["tr_3", "tr_6"]
    assert result.plan.days[0].items[0].start_time == "09:00"
    assert result.plan.days[0].items[0].id == "it_1"


def test_add_transport_option_with_choose_false_changes_nothing_else():
    result = apply_edit(
        PLAN,
        edit(AddTransportOption(op="add_transport_option", option=flight(), choose=False)),
        REQ,
    )
    assert option_of(result.plan, "tr_6").chosen is False
    assert option_of(result.plan, "tr_1").chosen is True
    assert result.plan.days == PLAN.days


def test_add_transport_option_ignores_a_chosen_flag_from_the_model():
    option = flight().model_copy(update={"chosen": True, "id": "tr_1"})
    result = apply_edit(
        PLAN, edit(AddTransportOption(op="add_transport_option", option=option)), REQ
    )
    assert (
        option_of(result.plan, "tr_1").chosen is True
        and option_of(result.plan, "tr_6").chosen is False
    )


def test_choosing_an_option_adds_the_linked_item_when_it_is_missing():
    plan = PLAN.model_copy(
        update={
            "days": (
                PLAN.days[0].model_copy(update={"items": PLAN.days[0].items[1:]}),
                *PLAN.days[1:],
            )
        }
    )
    result = apply_edit(
        plan, edit(ChooseTransportOption(op="choose_transport_option", option_id="tr_2")), REQ
    )
    first = result.plan.days[0].items[0]
    assert (first.option_id, first.id) == ("tr_2", "it_17")


def test_removing_a_transport_option_item_is_rejected():
    with pytest.raises(EditRejected) as raised:
        apply_edit(PLAN, edit(RemoveItem(op="remove_item", item_id="it_1")), REQ)
    assert "choose another option" in raised.value.errors[0]


def test_set_accommodation_by_id_unchooses_the_other():
    result = apply_edit(
        PLAN, edit(SetAccommodation(op="set_accommodation", accommodation_id="ac_2")), REQ
    )
    assert [(a.id, a.chosen) for a in result.plan.accommodation] == [
        ("ac_1", False),
        ("ac_2", True),
    ]
    assert result.changed == ["Set accommodation ac_2 Pine Hill Homestay"]


def test_set_accommodation_with_a_new_stay_adds_and_chooses_it():
    stay = Accommodation(
        name="Hotel Mới",
        check_in=date(2026, 12, 20),
        check_out=date(2026, 12, 23),
        price_per_night=Decimal(800000),
    )
    result = apply_edit(
        PLAN, edit(SetAccommodation(op="set_accommodation", accommodation=stay)), REQ
    )
    assert [(a.id, a.chosen) for a in result.plan.accommodation] == [
        ("ac_1", False),
        ("ac_2", False),
        ("ac_3", True),
    ]


def test_set_accommodation_needs_exactly_one_of_id_and_stay():
    with pytest.raises(ValidationError):
        SetAccommodation(op="set_accommodation")
    with pytest.raises(EditRejected):
        apply_edit(
            PLAN, edit(SetAccommodation(op="set_accommodation", accommodation_id="ac_9")), REQ
        )


def test_set_accommodation_outside_the_trip_is_rejected():
    stay = Accommodation(
        name="Hotel",
        check_in=date(2026, 12, 19),
        check_out=date(2026, 12, 23),
        price_per_night=Decimal(1),
    )
    with pytest.raises(EditRejected):
        apply_edit(PLAN, edit(SetAccommodation(op="set_accommodation", accommodation=stay)), REQ)


def test_replace_day_swaps_items_and_keeps_the_linked_transport_item():
    items = (
        PlanItem(title="Cà phê", category="food", start_time="09:00"),
        PlanItem(id="it_99", title="Ăn tối", category="food", start_time="19:00"),
    )
    result = apply_edit(
        PLAN, edit(ReplaceDay(op="replace_day", date=date(2026, 12, 23), items=items)), REQ
    )
    last = result.plan.days[3].items
    assert [(i.id, i.title) for i in last] == [
        ("it_17", "Cà phê"),
        ("it_16", last[1].title),
        ("it_18", "Ăn tối"),
    ]
    assert last[1].option_id == "tr_3"
    assert result.plan.days[:3] == PLAN.days[:3]
    assert check_plan(result.plan, REQ, DALAT_SOURCE_IDS).errors == []


def test_replace_day_keeps_the_ids_of_items_that_stay():
    kept = PLAN.days[1].items[0]
    result = apply_edit(
        PLAN, edit(ReplaceDay(op="replace_day", date=date(2026, 12, 21), items=(kept, kept))), REQ
    )
    assert [i.id for i in result.plan.days[1].items] == ["it_5", "it_17"]


def test_update_checklist_keeps_known_ids_and_assigns_new_ones():
    entries = (
        PLAN.checklist[1].model_copy(update={"done": True}),
        ChecklistItem(id="ck_50", label="Mang ô"),
    )
    result = apply_edit(PLAN, edit(UpdateChecklist(op="update_checklist", items=entries)), REQ)
    assert [(c.id, c.label, c.done) for c in result.plan.checklist] == [
        ("ck_2", "Thuê xe máy hai ngày", True),
        ("ck_3", "Mang ô", False),
    ]


def test_update_request_alone_returns_request_changes_and_same_plan():
    changes = RequestChanges(travelers=6, origin="Hà Nội")
    result = apply_edit(PLAN, edit(UpdateRequest(op="update_request", changes=changes)), REQ)
    assert result.plan is PLAN
    assert result.request_changes == changes
    assert result.changed == ["Updated request: origin, travelers"]


def test_update_request_mixed_with_other_ops_is_rejected():
    ops = (
        UpdateRequest(op="update_request", changes=RequestChanges(travelers=6)),
        RemoveItem(op="remove_item", item_id="it_8"),
    )
    with pytest.raises(EditRejected):
        apply_edit(PLAN, edit(*ops), REQ)


def test_update_request_with_no_change_is_rejected():
    with pytest.raises(EditRejected):
        apply_edit(PLAN, edit(UpdateRequest(op="update_request", changes=RequestChanges())), REQ)


def test_apply_edit_does_not_mutate_input_plan():
    snapshot = PLAN.model_dump()
    ops = (
        RemoveItem(op="remove_item", item_id="it_8"),
        ChooseTransportOption(op="choose_transport_option", option_id="tr_2"),
        SetAccommodation(op="set_accommodation", accommodation_id="ac_2"),
    )
    apply_edit(PLAN, edit(*ops), REQ)
    assert PLAN.model_dump() == snapshot


def test_ops_run_in_order_so_an_added_item_can_be_updated_by_a_later_op():
    new = PlanItem(title="Mới", category="food", start_time="10:00")
    ops = (
        AddItem(op="add_item", date=date(2026, 12, 21), item=new),
        UpdateItem(op="update_item", item_id="it_17", changes=ItemChanges(title="Mới hơn")),
    )
    result = apply_edit(PLAN, edit(*ops), REQ)
    assert item_of(result.plan, "it_17").title == "Mới hơn"


def test_abroad_choose_return_option_keeps_the_plan_valid():
    plan, request = bangkok_plan(), bangkok_request()
    result = apply_edit(
        plan, edit(ChooseTransportOption(op="choose_transport_option", option_id="tr_4")), request
    )
    last = result.plan.days[-1].items[-1]
    assert (last.option_id, last.price_currency, last.start_time) == ("tr_4", "VND", "20:00")
    assert check_plan(result.plan, request, BANGKOK_SOURCE_IDS).errors == []


def test_plan_edit_needs_one_to_twenty_ops():
    with pytest.raises(ValidationError):
        PlanEdit(ops=(), explanation="x")
    ops = tuple(RemoveItem(op="remove_item", item_id=f"it_{n}") for n in range(21))
    with pytest.raises(ValidationError):
        PlanEdit(ops=ops, explanation="x")


def test_plan_edit_parses_from_model_json_by_op_name():
    parsed = PlanEdit.model_validate_json(
        '{"ops": [{"op": "remove_item", "item_id": "it_8"}, '
        '{"op": "choose_transport_option", "option_id": "tr_2"}], "explanation": "ok"}'
    )
    assert [type(o).__name__ for o in parsed.ops] == ["RemoveItem", "ChooseTransportOption"]
    assert "oneOf" in str(PlanEdit.model_json_schema())
