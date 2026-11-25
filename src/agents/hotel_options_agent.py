"""Hotel options agent: a short reply and hotel cards from booking-site search results.

One LLM call (purpose ``answer``), parsed and repaired once by ``call_json``. The caller searches,
renders the prompt content, and keeps only the cards whose source it knows."""

from __future__ import annotations

from agents.base_agent import BaseAgent
from core.prompts import hotel_options_prompt
from domain.hotels import HotelOptionsReply
from models.model_router import CallContext


class HotelOptionsAgent(BaseAgent):
    # Write the reply and the cards; content is the tagged prompt with the search results
    def run(self, content: str, ctx: CallContext) -> HotelOptionsReply:
        return self.ask_json("answer", hotel_options_prompt, HotelOptionsReply, content, ctx)
