"""Discover suggest agent: a short reply and up to MAX_CARDS destination cards from search hits.

One LLM call (purpose ``suggest``). The caller searches and renders the hits; this agent
builds the prompt, repairs once when no card is usable, and returns cards already cleaned."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from agents.base_agent import BaseAgent
from core.prompts import discovery_suggest_prompt
from domain.discovery import (
    HIDDEN_FIELDS,
    MAX_CARDS,
    SuggestionsReply,
    discovery_content,
    usable_cards,
)
from models.model_router import CallContext


class DiscoverSuggestAgent(BaseAgent):
    # Write the reply and the cards from the sources; known_source_ids are the ids the research holds
    # conversation is the rendered <conversation> block, "" when there is none
    def run(
        self,
        draft: Mapping[str, Any],
        today: date,
        conversation: str,
        sources: str,
        known_source_ids: frozenset[int],
        message: str,
        ctx: CallContext,
    ) -> SuggestionsReply:
        # A card with an unsupported country is dropped; no card left is an error to repair
        def check(value: SuggestionsReply) -> list[str]:
            if usable_cards(value.cards, known_source_ids):
                return []
            return [
                "cards: none has a country_code that is the ISO 3166-1 code of a country "
                "the place is in"
            ]

        content = discovery_content(today, draft, conversation, message, sources)
        reply = self.ask_json(
            "suggest",
            discovery_suggest_prompt,
            SuggestionsReply,
            content,
            ctx,
            check,
            HIDDEN_FIELDS,
        )
        cards = usable_cards(reply.cards, known_source_ids)[:MAX_CARDS]
        return reply.model_copy(update={"cards": cards})
