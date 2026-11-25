"""The fixed questionnaire that draws out what a visitor wants before suggesting destinations.

Six steps in a fixed order; each button id maps to draft fields here, in one place. The frontend
sends button ids, never values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from domain.discovery import RequestDraft
from domain.trip_request import NOTES_MAX_LEN, clean_text

STEPS: tuple[str, ...] = ("styles", "travelers", "budget", "origin", "when", "length")
# Draft fields a visitor may type in at each step instead of pressing a button
TYPED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "styles": ("travel_styles",),
    "travelers": ("travelers",),
    "budget": ("budget_amount",),
    "origin": ("origin",),
    "when": ("start_date",),
    "length": ("length_days", "notes"),
}
# Draft fields the card shows as already answered
ANSWER_FIELDS = (
    "travel_styles", "travelers", "budget_amount", "budget_scope", "origin", "month",
    "start_date", "length_days", "notes",
)  # fmt: skip
MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip

STYLE_IDS = ("relax", "adventure", "culture", "food", "nature", "nightlife", "shopping")
TRAVELERS = {"1": 1, "2": 2, "3_4": 4, "5_plus": 5}
# Budget per person in VND, and the style it adds
BUDGETS: Mapping[str, tuple[Decimal, list[str]]] = {
    "saver": (Decimal("3000000"), ["budget"]),
    "moderate": (Decimal("6000000"), []),
    "comfort": (Decimal("12000000"), []),
    "premium": (Decimal("25000000"), ["luxury"]),
}
ORIGINS = {"hanoi": "Hà Nội", "hcmc": "TP. Hồ Chí Minh", "danang": "Đà Nẵng"}
# The starting point when the visitor's location is unknown and nothing else names one
DEFAULT_ORIGIN = ORIGINS["hanoi"]
HOLIDAY_MONTHS = {
    "holiday_30_4": "April",
    "holiday_2_9": "September",
    "holiday_new_year": "January",
    "christmas": "December",
}
LENGTHS = {"2_3": 3, "4_5": 5, "week": 7, "longer": 10}

OPTIONS: Mapping[str, tuple[str, ...]] = {
    "styles": STYLE_IDS,
    "travelers": tuple(TRAVELERS),
    "budget": tuple(BUDGETS),
    "origin": tuple(ORIGINS),
    "when": ("this_month", "next_month", *HOLIDAY_MONTHS),
    "length": tuple(LENGTHS),
}


# The draft fields one answer sets: from a button id, or from what the visitor typed when choice is
# None (an empty typed with no choice is a skipped step). The last step also takes typed notes next
# to a button. Raises ValueError on anything else
def answer_for(
    step: int, choice: str | list[str] | None, typed: Mapping[str, Any], today: date
) -> dict[str, Any]:
    if not 1 <= step <= len(STEPS):
        raise ValueError(f"step must be 1 to {len(STEPS)}")
    name = STEPS[step - 1]
    if choice is None:
        return _typed_answer(name, typed, today)
    if name == "length" and set(typed) <= {"notes"}:
        return _button_answer(name, choice, today) | _typed_answer(name, typed, today)
    if typed:
        raise ValueError(f"{name} takes a button or typed values, not both")
    return _button_answer(name, choice, today)


# The draft fields of one button
def _button_answer(name: str, choice: str | list[str], today: date) -> dict[str, Any]:
    if name == "styles":
        if not isinstance(choice, list) or not choice or set(choice) - set(STYLE_IDS):
            raise ValueError(f"styles must be a non-empty list of {STYLE_IDS}")
        return {"travel_styles": list(dict.fromkeys(choice))}
    if not isinstance(choice, str) or choice not in OPTIONS[name]:
        raise ValueError(f"{name} must be one of {OPTIONS[name]}")
    if name == "travelers":
        return {"travelers": TRAVELERS[choice]}
    if name == "budget":
        amount, styles = BUDGETS[choice]
        out: dict[str, Any] = {"budget_amount": amount, "budget_scope": "per_person"}
        return out | ({"travel_styles": styles} if styles else {})
    if name == "origin":
        return {"origin": ORIGINS[choice]}
    if name == "when":
        return {"month": _month_for(choice, today)}
    return {"length_days": LENGTHS[choice]}


# The month a "when" button means
def _month_for(choice: str, today: date) -> str:
    if choice == "this_month":
        return MONTHS[today.month - 1]
    if choice == "next_month":
        return MONTHS[today.month % 12]
    return HOLIDAY_MONTHS[choice]


# Validate typed values with the draft's own field rules
def _typed_answer(name: str, typed: Mapping[str, Any], today: date) -> dict[str, Any]:
    allowed = TYPED_FIELDS[name]
    if set(typed) - set(allowed):
        raise ValueError(f"{name} accepts only {allowed}")
    try:
        draft = RequestDraft.model_validate(dict(typed))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    out = {k: getattr(draft, k) for k in typed}
    if out.get("notes") is not None:
        out["notes"] = clean_text(out["notes"], NOTES_MAX_LEN) or None
    if "travel_styles" in out:
        out["travel_styles"] = list(out["travel_styles"])
    if out.get("start_date") is not None and out["start_date"] < today:
        raise ValueError("start_date must not be in the past")
    if "budget_amount" in out:
        out["budget_scope"] = "per_person"
    return out


# Whether the draft already answers a step
def _answered(name: str, draft: Mapping[str, Any]) -> bool:
    if name == "styles":
        return bool(draft.get("travel_styles"))
    if name == "when":
        return bool(draft.get("month") or draft.get("start_date"))
    if name == "length":
        return bool(draft.get("length_days") or (draft.get("start_date") and draft.get("end_date")))
    field = {"travelers": "travelers", "budget": "budget_amount", "origin": "origin"}[name]
    return draft.get(field) is not None


# The first step (1-6) the draft does not answer yet; None when it answers all six
def first_missing_step(draft: Mapping[str, Any]) -> int | None:
    return next((n for n, name in enumerate(STEPS, 1) if not _answered(name, draft)), None)


# A new open questionnaire card that starts at the first step the draft does not answer
def questionnaire_metadata(draft: Mapping[str, Any]) -> dict[str, Any]:
    missing = first_missing_step(draft)
    return {
        "kind": "questionnaire",
        "status": "open",
        "step": len(STEPS) if missing is None else missing - 1,
        "answers": {k: draft[k] for k in ANSWER_FIELDS if draft.get(k) not in (None, [], "")},
        "choices": {},
    }
