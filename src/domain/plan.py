"""The plan document: one trip's itinerary, transport, stay, checklist and warnings."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from domain.currency import Currencies
from domain.trip_request import TransportMode

Category = Literal["transport", "accommodation", "food", "shopping", "service", "sightseeing"]
PriceBasis = Literal["source", "estimate"]
ItemStatus = Literal["planned", "booked", "paid"]
WeatherBasis = Literal["forecast", "typical"]
Leg = Literal["outbound", "return", "local"]
IdPrefix = Literal["it", "tr", "ac", "ck"]

# Names of the six template categories, in the order the Summary sheet lists them
CATEGORY_LABELS_VI: Mapping[Category, str] = {
    "transport": "Đi lại",
    "accommodation": "Lưu trú",
    "food": "Ăn uống",
    "shopping": "Mua sắm",
    "service": "Dịch vụ",
    "sightseeing": "Thăm quan",
}

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
DEPART_PATTERN = r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$"


# A whole amount stays an integer in JSON (350), others a float (12.5), as the frontend reads them
def _money_json(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    PlainSerializer(_money_json, return_type=float, when_used="json"),
]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
TimeOfDay = Annotated[str, Field(pattern=TIME_PATTERN)]


# Base of every plan model: immutable
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# Weather for one day, from research and never set by the model
class Weather(_Frozen):
    summary: str
    temp_min_c: float
    temp_max_c: float
    precip_mm: float = Field(ge=0)
    basis: WeatherBasis


# One thing to do on one day; id and option_id are set by code
class PlanItem(_Frozen):
    id: str = ""
    start_time: TimeOfDay | None = None
    end_time: TimeOfDay | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    location: str | None = None
    category: Category
    transport_mode: TransportMode | None = None
    price_per_person: Money = Decimal(0)
    price_currency: CurrencyCode = "VND"
    price_basis: PriceBasis = "estimate"
    source_id: int | None = None
    status: ItemStatus = "planned"
    note: str | None = None
    option_id: str | None = None


# One date of the trip with its items in time order
class Day(_Frozen):
    date: date
    theme: str = ""
    weather: Weather | None = None
    items: tuple[PlanItem, ...] = ()


# One way to get there, back or around; the chosen outbound and return ones also appear as items
class TransportOption(_Frozen):
    id: str = ""
    leg: Leg
    mode: TransportMode
    summary: str = Field(min_length=1)
    depart: str | None = Field(default=None, pattern=DEPART_PATTERN)
    duration_minutes: int | None = Field(default=None, ge=0)
    price_per_person: Money = Decimal(0)
    price_currency: CurrencyCode = "VND"
    price_basis: PriceBasis = "estimate"
    source_id: int | None = None
    pros: str = ""
    cons: str = ""
    chosen: bool = False


# One place to stay; only the chosen one is costed
class Accommodation(_Frozen):
    id: str = ""
    name: str = Field(min_length=1)
    area: str = ""
    check_in: date
    check_out: date
    price_per_night: Money
    price_currency: CurrencyCode = "VND"
    rooms: int = Field(default=1, ge=1)
    price_basis: PriceBasis = "estimate"
    source_id: int | None = None
    chosen: bool = False

    # A stay has at least one night
    @model_validator(mode="after")
    def _check_out_after_check_in(self) -> Self:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self


# One thing to do or buy before leaving
class ChecklistItem(_Frozen):
    id: str = ""
    label: str = Field(min_length=1)
    category: Category = "service"
    price_per_person: Money = Decimal(0)
    price_currency: CurrencyCode = "VND"
    done: bool = False


# A notice for the visitor, such as over_budget
class PlanWarning(_Frozen):
    code: str
    message: str


# The whole document stored in trips.plan
class Plan(_Frozen):
    title: str = Field(min_length=1)
    summary: str = ""
    currencies: Currencies
    days: tuple[Day, ...]
    transport_options: tuple[TransportOption, ...] = ()
    accommodation: tuple[Accommodation, ...] = ()
    checklist: tuple[ChecklistItem, ...] = ()
    warnings: tuple[PlanWarning, ...] = ()


# The id numbers already used with a prefix, such as it_3 -> 3
def _used_numbers(ids: Sequence[str], prefix: IdPrefix) -> list[int]:
    return [int(m.group(1)) for i in ids if (m := re.fullmatch(rf"{prefix}_(\d+)", i))]


# Every id of one prefix in the plan
def _ids_of(plan: Plan, prefix: IdPrefix) -> list[str]:
    match prefix:
        case "it":
            return [item.id for day in plan.days for item in day.items]
        case "tr":
            return [o.id for o in plan.transport_options]
        case "ac":
            return [a.id for a in plan.accommodation]
        case "ck":
            return [c.id for c in plan.checklist]


# The next unused id of a prefix: one more than the highest number in the plan
def next_id(plan: Plan, prefix: IdPrefix) -> str:
    return f"{prefix}_{max(_used_numbers(_ids_of(plan, prefix), prefix), default=0) + 1}"


# Fill every empty id with the next free one; existing ids never change
def assign_ids(plan: Plan) -> Plan:
    counters = {
        p: max(_used_numbers(_ids_of(plan, p), p), default=0) for p in ("it", "tr", "ac", "ck")
    }

    # Give an empty-id object its prefix and next number
    def fill[M: (PlanItem, TransportOption, Accommodation, ChecklistItem)](
        obj: M, prefix: IdPrefix
    ) -> M:
        if obj.id:
            return obj
        counters[prefix] += 1
        return obj.model_copy(update={"id": f"{prefix}_{counters[prefix]}"})

    days = tuple(
        day.model_copy(update={"items": tuple(fill(i, "it") for i in day.items)})
        for day in plan.days
    )
    return plan.model_copy(
        update={
            "days": days,
            "transport_options": tuple(fill(o, "tr") for o in plan.transport_options),
            "accommodation": tuple(fill(a, "ac") for a in plan.accommodation),
            "checklist": tuple(fill(c, "ck") for c in plan.checklist),
        }
    )


# The itinerary item that stands for a chosen transport option on the given day
def transport_item(option: TransportOption, day: date) -> PlanItem:
    start = end = None
    if option.depart is not None and option.depart.startswith(day.isoformat()):
        start = option.depart[11:16]
        if option.duration_minutes is not None:
            minutes = int(start[:2]) * 60 + int(start[3:]) + option.duration_minutes
            if minutes < 24 * 60:
                end = f"{minutes // 60:02d}:{minutes % 60:02d}"
    return PlanItem(
        start_time=start,
        end_time=end,
        title=option.summary,
        description=option.pros or None,
        category="transport",
        transport_mode=option.mode,
        price_per_person=option.price_per_person,
        price_currency=option.price_currency,
        price_basis=option.price_basis,
        source_id=option.source_id,
        option_id=option.id,
    )
