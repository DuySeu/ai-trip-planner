"""Flight options agent: a short reply and ticket cards from ticket-site search results.

One LLM call (purpose ``answer``), parsed and repaired once by ``call_json``. The caller searches,
renders the prompt content, and keeps only the cards whose source it knows."""

from __future__ import annotations

from agents.base_agent import BaseAgent
from core.prompts import flight_options_prompt
from domain.flights import FlightOptionsReply
from models.model_router import CallContext


class FlightOptionsAgent(BaseAgent):
    # Write the reply and the cards; content is the tagged prompt with the search results
    def run(self, content: str, ctx: CallContext) -> FlightOptionsReply:
        return self.ask_json("answer", flight_options_prompt, FlightOptionsReply, content, ctx)
