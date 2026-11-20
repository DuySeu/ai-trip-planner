"""Flight options agent: a short reply and ticket cards from ticket-site search results.

One LLM call (purpose ``answer``), parsed and repaired once by ``call_json``. The caller searches,
renders the prompt content, and keeps only the cards whose source it knows."""

from __future__ import annotations

from core.prompts import flight_options_prompt
from domain.flights import FlightOptionsReply
from models.model_router import CallContext, ModelRouter, call_json, compact_schema


class FlightOptionsAgent:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    # Write the reply and the cards; content is the tagged prompt with the search results
    def run(self, content: str, ctx: CallContext) -> FlightOptionsReply:
        system = flight_options_prompt.format(schema=compact_schema(FlightOptionsReply, {}))
        return call_json(
            self.router,
            "answer",
            system,
            [{"role": "user", "content": content}],
            FlightOptionsReply,
            None,
            ctx,
        ).value
