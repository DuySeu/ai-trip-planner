"""Hotel options agent: a short reply and hotel cards from booking-site search results.

One LLM call (purpose ``answer``), parsed and repaired once by ``call_json``. The caller searches,
renders the prompt content, and keeps only the cards whose source it knows."""

from __future__ import annotations

from core.prompts import hotel_options_prompt
from domain.hotels import HotelOptionsReply
from models.model_router import CallContext, ModelRouter, call_json, compact_schema


class HotelOptionsAgent:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    # Write the reply and the cards; content is the tagged prompt with the search results
    def run(self, content: str, ctx: CallContext) -> HotelOptionsReply:
        system = hotel_options_prompt.format(schema=compact_schema(HotelOptionsReply, {}))
        return call_json(
            self.router,
            "answer",
            system,
            [{"role": "user", "content": content}],
            HotelOptionsReply,
            None,
            ctx,
        ).value
