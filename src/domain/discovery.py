"""What a discovery turn knows and says: the trip draft, the model's replies and the suggestion cards."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.constants import COUNTRY_CURRENCY
from domain.trip_request import (
    BudgetScope,
    Destination,
    Language,
    PlaceText,
    TravelStyle,
)

MAX_CARDS = 3
# Fields the model must not see in the schema
HIDDEN_FIELDS = {"RequestDraft": {"destination"}, "TripFormExtract": {"destination"}}


# Base of every discovery model: immutable
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# What is known about the trip so far; every field of a TripRequest is optional here
class RequestDraft(_Frozen):
    destination: Destination | None = None
    origin: PlaceText | None = None
    start_date: date | None = None
    end_date: date | None = None
    month: str | None = None
    length_days: int | None = Field(default=None, ge=1, le=30)
    travelers: int | None = Field(default=None, ge=1, le=50)
    travel_styles: tuple[TravelStyle, ...] = ()
    budget_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    budget_scope: BudgetScope | None = None
    language: Language | None = None
    notes: str | None = None


# What the model reads off the chat for a trip form; code turns destination_name into a destination
class TripFormExtract(RequestDraft):
    destination_name: PlaceText | None = None


# The model's answer for an ask or answer turn: what to say, what it learned
class DiscoveryReply(_Frozen):
    reply: str = Field(min_length=1)
    request_draft: RequestDraft = RequestDraft()


# One suggested destination; the cost is always an estimate
class SuggestionCard(_Frozen):
    name: str = Field(min_length=1)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    why: str = Field(min_length=1)
    length_days: int = Field(ge=1, le=30)
    est_cost_per_person_vnd: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    best_months: tuple[str, ...] = ()
    highlights: tuple[str, ...] = ()
    source_ids: tuple[int, ...] = ()


# The model's answer for a suggest turn: what it assumes, what it learned, and the cards
class SuggestionsReply(DiscoveryReply):
    cards: tuple[SuggestionCard, ...] = Field(min_length=1)


# The draft with what the model learned this turn laid over what was known; nothing is forgotten
def merge_draft(old: Mapping[str, Any], new: RequestDraft) -> dict[str, Any]:
    learned = {k: v for k, v in new.model_dump(mode="json").items() if v not in (None, [], "")}
    return {**old, **learned}


# The cards worth showing: a supported country, and only source ids the research really holds
def usable_cards(
    cards: tuple[SuggestionCard, ...], known: frozenset[int]
) -> tuple[SuggestionCard, ...]:
    return tuple(
        c.model_copy(update={"source_ids": tuple(i for i in c.source_ids if i in known)})
        for c in cards
        if c.country_code in COUNTRY_CURRENCY
    )


# The user message of a discovery call: the tagged context in a fixed order, empty parts left out
# sources is None for the actions that do not search
def discovery_content(
    today: date,
    draft: Mapping[str, Any],
    conversation: str,
    message: str,
    sources: str | None = None,
) -> str:
    parts = [
        f"<today>{today.isoformat()}</today>",
        f"<draft>\n{json.dumps(draft, ensure_ascii=False, default=str)}\n</draft>",
        f"<sources>\n{sources or 'none'}\n</sources>" if sources is not None else "",
        conversation,
        f"<request>\n{message}\n</request>",
    ]
    return "\n\n".join(p for p in parts if p)
