"""Create trip agent: read what the visitor already said in the chat, for a prefilled trip form.

One LLM call (purpose ``discover``), no search. The destination is only a name here; the caller
looks up its coordinates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from core.prompts import create_trip_prompt
from domain.discovery import HIDDEN_FIELDS, TripFormExtract, discovery_content
from models.model_router import CallContext, ModelRouter, call_json, compact_schema


class CreateTripAgent:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    # Read the trip fields the chat already holds
    # conversation is the rendered <conversation> block, "" when there is none
    def run(
        self,
        draft: Mapping[str, Any],
        today: date,
        conversation: str,
        message: str,
        ctx: CallContext,
    ) -> TripFormExtract:
        system = create_trip_prompt.format(schema=compact_schema(TripFormExtract, HIDDEN_FIELDS))
        content = discovery_content(today, draft, conversation, message)
        return call_json(
            self.router,
            "discover",
            system,
            [{"role": "user", "content": content}],
            TripFormExtract,
            None,
            ctx,
        ).value


# The extract without its dates when they start before today; the model sometimes invents them
def drop_past_dates(extract: TripFormExtract, today: date) -> TripFormExtract:
    if extract.start_date is not None and extract.start_date < today:
        return extract.model_copy(update={"start_date": None, "end_date": None})
    return extract
