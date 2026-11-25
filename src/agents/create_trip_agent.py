"""Create trip agent: read what the visitor already said in the chat, for a prefilled trip form.

One LLM call (purpose ``discover``), no search. The destination is only a name here; the caller
looks up its coordinates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from agents.base_agent import BaseAgent
from core.prompts import create_trip_prompt
from domain.discovery import HIDDEN_FIELDS, TripFormExtract, discovery_content
from models.model_router import CallContext


class CreateTripAgent(BaseAgent):
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
        content = discovery_content(today, draft, conversation, message)
        return self.ask_json(
            "discover", create_trip_prompt, TripFormExtract, content, ctx, drop=HIDDEN_FIELDS
        )


# The extract without its dates when they start before today; the model sometimes invents them
def drop_past_dates(extract: TripFormExtract, today: date) -> TripFormExtract:
    if extract.start_date is not None and extract.start_date < today:
        return extract.model_copy(update={"start_date": None, "end_date": None})
    return extract
