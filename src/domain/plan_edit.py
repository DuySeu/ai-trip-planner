"""Edits to a plan as a short list of operations, validated and applied by code."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from domain.plan import (
    Accommodation,
    Category,
    ChecklistItem,
    ItemStatus,
    Money,
    Plan,
    PlanItem,
    PriceBasis,
    TimeOfDay,
    TransportOption,
    assign_ids,
    next_id,
    transport_item,
)
from domain.trip_request import Language, PlaceText, TransportMode, TripRequest

MAX_OPS = 20


# Base of every edit model: immutable
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# Why an edit cannot be applied, as short sentences for the model to repair
class EditRejected(Exception):
    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


# Item fields an edit may change: null means unchanged, and text is cleared with ""
class ItemChanges(_Frozen):
    start_time: TimeOfDay | None = None
    end_time: TimeOfDay | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    location: str | None = None
    category: Category | None = None
    transport_mode: TransportMode | None = None
    price_per_person: Money | None = None
    price_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    price_basis: PriceBasis | None = None
    source_id: int | None = None
    status: ItemStatus | None = None
    note: str | None = None


# Trip request fields the chat may change; a new request needs a new plan
class RequestChanges(_Frozen):
    start_date: date | None = None
    end_date: date | None = None
    travelers: int | None = Field(default=None, ge=1, le=50)
    origin: PlaceText | None = None
    language: Language | None = None


class AddItem(_Frozen):
    op: Literal["add_item"]
    date: date
    item: PlanItem


class UpdateItem(_Frozen):
    op: Literal["update_item"]
    item_id: str
    changes: ItemChanges


class RemoveItem(_Frozen):
    op: Literal["remove_item"]
    item_id: str


# Move an item to another day or time; a null time stays as it is
class MoveItem(_Frozen):
    op: Literal["move_item"]
    item_id: str
    date: date
    start_time: TimeOfDay | None = None
    end_time: TimeOfDay | None = None


# Choose a listed stay by id, or add a new one and choose it
class SetAccommodation(_Frozen):
    op: Literal["set_accommodation"]
    accommodation_id: str | None = None
    accommodation: Accommodation | None = None

    # Exactly one of the two is set
    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.accommodation_id is None) == (self.accommodation is None):
            raise ValueError("set exactly one of accommodation_id and accommodation")
        return self


class ChooseTransportOption(_Frozen):
    op: Literal["choose_transport_option"]
    option_id: str


class AddTransportOption(_Frozen):
    op: Literal["add_transport_option"]
    option: TransportOption
    choose: bool = False


class ReplaceDay(_Frozen):
    op: Literal["replace_day"]
    date: date
    items: tuple[PlanItem, ...]


class UpdateChecklist(_Frozen):
    op: Literal["update_checklist"]
    items: tuple[ChecklistItem, ...]


class UpdateRequest(_Frozen):
    op: Literal["update_request"]
    changes: RequestChanges


EditOp = Annotated[
    AddItem
    | UpdateItem
    | RemoveItem
    | MoveItem
    | SetAccommodation
    | ChooseTransportOption
    | AddTransportOption
    | ReplaceDay
    | UpdateChecklist
    | UpdateRequest,
    Field(discriminator="op"),
]


# What the model asks for: 1 to 20 operations and a short explanation for the visitor
class PlanEdit(_Frozen):
    ops: tuple[EditOp, ...] = Field(min_length=1, max_length=MAX_OPS)
    explanation: str


# The edited plan, request changes for a re-plan, and one line per operation
@dataclass(frozen=True)
class EditResult:
    plan: Plan
    request_changes: RequestChanges | None
    changed: list[str]


# Apply the edit to a copy of the plan; raise EditRejected with every problem found
def apply_edit(plan: Plan, edit: PlanEdit, request: TripRequest) -> EditResult:
    requests = [op for op in edit.ops if isinstance(op, UpdateRequest)]
    if requests:
        if len(edit.ops) > 1:
            raise EditRejected(["update_request must be the only operation in an edit"])
        changes = requests[0].changes
        fields = sorted(changes.model_dump(exclude_none=True))
        if not fields:
            raise EditRejected(["update_request changes nothing"])
        return EditResult(plan, changes, [f"Updated request: {', '.join(fields)}"])

    errors: list[str] = []
    changed: list[str] = []
    for op in edit.ops:
        try:
            plan, line = _apply_op(plan, op, request)
        except EditRejected as rejected:
            errors += rejected.errors
        except ValidationError as invalid:
            errors += [
                f"{op.op}: {e['loc'][0] if e['loc'] else 'value'} {e['msg']}"
                for e in invalid.errors()
            ]
        else:
            changed.append(line)
    if errors:
        raise EditRejected(errors)
    return EditResult(assign_ids(plan), None, changed)


# Apply one operation and describe it
def _apply_op(plan: Plan, op: EditOp, request: TripRequest) -> tuple[Plan, str]:
    match op:
        case AddItem():
            day = _day_index(plan, request, op.date, op.op)
            item = op.item.model_copy(update={"id": next_id(plan, "it"), "option_id": None})
            plan = _set_items(plan, day, _insert_sorted(plan.days[day].items, item))
            return plan, f"Added {item.id} {item.title} on {op.date.isoformat()}"

        case UpdateItem():
            day, pos = _find_item(plan, op.item_id, op.op)
            old = plan.days[day].items[pos]
            fields = op.changes.model_dump(exclude_none=True)
            new = PlanItem.model_validate({**old.model_dump(), **fields})
            return _swap_item(plan, day, pos, new), f"Updated {new.id} {new.title}"

        case RemoveItem():
            day, pos = _find_item(plan, op.item_id, op.op)
            old = plan.days[day].items[pos]
            if old.option_id:
                raise EditRejected(
                    [
                        f"remove_item: {old.id} stands for transport option {old.option_id}, "
                        "choose another option instead"
                    ]
                )
            plan = _set_items(plan, day, _without(plan.days[day].items, pos))
            return plan, f"Removed {old.id} {old.title}"

        case MoveItem():
            target = _day_index(plan, request, op.date, op.op)
            day, pos = _find_item(plan, op.item_id, op.op)
            item = plan.days[day].items[pos]
            times = {
                k: v for k, v in (("start_time", op.start_time), ("end_time", op.end_time)) if v
            }
            item = PlanItem.model_validate({**item.model_dump(), **times})
            plan = _set_items(plan, day, _without(plan.days[day].items, pos))
            plan = _set_items(plan, target, _insert_sorted(plan.days[target].items, item))
            return plan, f"Moved {item.id} {item.title} to {op.date.isoformat()}"

        case SetAccommodation():
            return _set_accommodation(plan, op, request)

        case ChooseTransportOption():
            return _choose_option(plan, op.option_id, request, op.op)

        case AddTransportOption():
            option = op.option.model_copy(update={"id": next_id(plan, "tr"), "chosen": False})
            plan = plan.model_copy(update={"transport_options": (*plan.transport_options, option)})
            if op.choose:
                return _choose_option(plan, option.id, request, op.op)
            return plan, f"Added {option.id} {option.summary} ({option.leg})"

        case ReplaceDay():
            return _replace_day(plan, op, request)

        case UpdateChecklist():
            known = {c.id for c in plan.checklist}
            entries = _keep_known_ids(op.items, known)
            plan = plan.model_copy(update={"checklist": entries})
            return plan, f"Updated checklist ({len(entries)} entries)"

        case UpdateRequest():
            raise EditRejected(["update_request must be the only operation in an edit"])


# Index of the plan's day for a date, rejecting dates outside the trip or without a day
def _day_index(plan: Plan, request: TripRequest, when: date, op: str) -> int:
    if not request.start_date <= when <= request.end_date:
        raise EditRejected(
            [
                f"{op}: {when.isoformat()} is outside the trip "
                f"({request.start_date.isoformat()} to {request.end_date.isoformat()})"
            ]
        )
    for index, day in enumerate(plan.days):
        if day.date == when:
            return index
    raise EditRejected([f"{op}: the plan has no day for {when.isoformat()}"])


# Day and position of an item id
def _find_item(plan: Plan, item_id: str, op: str) -> tuple[int, int]:
    for d, day in enumerate(plan.days):
        for p, item in enumerate(day.items):
            if item.id == item_id:
                return d, p
    raise EditRejected([f"{op}: unknown item id {item_id}"])


# The plan with one day's items replaced
def _set_items(plan: Plan, index: int, items: tuple[PlanItem, ...]) -> Plan:
    days = list(plan.days)
    days[index] = days[index].model_copy(update={"items": items})
    return plan.model_copy(update={"days": tuple(days)})


# The items without the one at a position
def _without(items: tuple[PlanItem, ...], pos: int) -> tuple[PlanItem, ...]:
    return items[:pos] + items[pos + 1 :]


# The plan with the item at a position replaced
def _swap_item(plan: Plan, day: int, pos: int, item: PlanItem) -> Plan:
    items = plan.days[day].items
    return _set_items(plan, day, (*items[:pos], item, *items[pos + 1 :]))


# Insert an item by start time after equal ones; an item without a start time goes last
def _insert_sorted(items: tuple[PlanItem, ...], item: PlanItem) -> tuple[PlanItem, ...]:
    if item.start_time is not None:
        for pos, other in enumerate(items):
            if other.start_time is not None and other.start_time > item.start_time:
                return (*items[:pos], item, *items[pos:])
    return (*items, item)


# Keep an id only when it exists already and appears once; others get a fresh one later
def _keep_known_ids[E: (PlanItem, ChecklistItem)](
    entries: Sequence[E], known: set[str]
) -> tuple[E, ...]:
    seen: set[str] = set()
    kept: list[E] = []
    for entry in entries:
        if entry.id in known and entry.id not in seen:
            seen.add(entry.id)
            kept.append(entry)
        else:
            kept.append(entry.model_copy(update={"id": ""}))
    return tuple(kept)


# Choose a listed stay or add a new one; only one stays chosen
def _set_accommodation(plan: Plan, op: SetAccommodation, request: TripRequest) -> tuple[Plan, str]:
    stays = plan.accommodation
    if op.accommodation_id is not None:
        if op.accommodation_id not in {a.id for a in stays}:
            raise EditRejected(
                [f"set_accommodation: unknown accommodation id {op.accommodation_id}"]
            )
        chosen_id = op.accommodation_id
    else:
        new = op.accommodation
        assert new is not None  # the model validator guarantees one of the two
        if new.check_in < request.start_date or new.check_out > request.end_date:
            raise EditRejected(["set_accommodation: the stay must lie inside the trip dates"])
        chosen_id = next_id(plan, "ac")
        stays = (*stays, new.model_copy(update={"id": chosen_id}))
    stays = tuple(a.model_copy(update={"chosen": a.id == chosen_id}) for a in stays)
    name = next(a.name for a in stays if a.id == chosen_id)
    return plan.model_copy(update={"accommodation": stays}), f"Set accommodation {chosen_id} {name}"


# Choose an option and swap the itinerary item that stands for the leg's chosen option
def _choose_option(plan: Plan, option_id: str, request: TripRequest, op: str) -> tuple[Plan, str]:
    option = next((o for o in plan.transport_options if o.id == option_id), None)
    if option is None:
        raise EditRejected([f"{op}: unknown transport option id {option_id}"])
    others = {o.id for o in plan.transport_options if o.leg == option.leg and o.id != option_id}
    options = tuple(
        o.model_copy(update={"chosen": o.id == option_id}) if o.leg == option.leg else o
        for o in plan.transport_options
    )
    plan = plan.model_copy(update={"transport_options": options})
    line = f"Chose {option_id} for {option.leg}"
    if option.leg == "local":
        return plan, line

    when = request.start_date if option.leg == "outbound" else request.end_date
    target = _day_index(plan, request, when, op)
    for d, day in enumerate(plan.days):
        for p, item in enumerate(day.items):
            if item.option_id in others | {option_id}:
                new = transport_item(option, day.date).model_copy(update={"id": item.id})
                return _swap_item(plan, d, p, new), line

    new = transport_item(option, plan.days[target].date).model_copy(
        update={"id": next_id(plan, "it")}
    )
    day_items = plan.days[target].items
    ordered = (new, *day_items) if option.leg == "outbound" else (*day_items, new)
    return _set_items(plan, target, ordered), line


# Replace one day's items, keeping the transport items that stand for chosen options
def _replace_day(plan: Plan, op: ReplaceDay, request: TripRequest) -> tuple[Plan, str]:
    day = _day_index(plan, request, op.date, op.op)
    old = plan.days[day].items
    known = {i.id for i in old if not i.option_id}
    items = _keep_known_ids([i.model_copy(update={"option_id": None}) for i in op.items], known)
    ordered = items
    for item in (i for i in old if i.option_id):
        if item.start_time is None and _leg_of(plan, item) == "outbound":
            ordered = (item, *ordered)
        else:
            ordered = _insert_sorted(ordered, item)
    return _set_items(
        plan, day, ordered
    ), f"Replaced day {op.date.isoformat()} ({len(items)} items)"


# The leg of the option a transport item stands for
def _leg_of(plan: Plan, item: PlanItem) -> str | None:
    return next((o.leg for o in plan.transport_options if o.id == item.option_id), None)
