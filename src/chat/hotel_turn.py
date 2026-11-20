"""A question about hotels: search the booking sites, then a short reply and hotel cards.

The cards go out as one ``hotels`` event and are saved in the assistant message's suggestions
(intent ``hotel_options``), so they come back when the page reloads."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from agents.hotel_options_agent import HotelOptionsAgent
from chat.events import ChatEvent, token_events
from chat.handlers import ChatContext, build_prompt, sources_text
from core.exceptions import ResearchFailed
from db.repositories import messages, research
from db.repositories.research import SourceInput, SourceRow
from domain.hotels import hotel_cards_out
from models.model_router import CallContext

if TYPE_CHECKING:
    # Imported for annotations only: chat_service imports this module
    from chat.chat_service import ChatDeps, ChatTurn

logger = logging.getLogger(__name__)


# Search, ask the model once, stream the reply, then send the cards; the message is saved when
# the stream ends, fails or is closed, with the cards only when the reply was sent whole
def run_hotel_turn(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext, query: str
) -> Iterator[ChatEvent]:
    try:
        hits = deps.search(query, "accommodation")
    except ResearchFailed as exc:
        logger.warning("hotel search failed: %s", exc)
        hits = []

    saved: list[SourceRow] = []
    if hits:
        with deps.pool.connection() as conn:
            saved = research.save_sources(
                conn,
                trip_id=turn.trip_id,
                conversation_id=None if turn.trip_id else turn.conversation_id,
                kind="accommodation",
                items=[SourceInput(h.title, h.url, h.content) for h in hits],
            )

    content = build_prompt(data, turn.message.content, search_results=sources_text(saved))
    result = HotelOptionsAgent(deps.router).run(content, call_ctx)
    cards = hotel_cards_out(result.cards, {s.id: s.url for s in saved if s.url})
    logger.info(
        "hotel options: %d results, model wrote %d cards, %d kept",
        len(hits),
        len(result.cards),
        len(cards),
    )

    spoken: list[str] = []
    suggestions: list[dict[str, Any]] | None = None
    try:
        for event in token_events(result.reply):
            spoken.append(event.data["text"])
            yield event
        if cards:
            suggestions = cards
            yield ChatEvent("hotels", {"cards": cards})
    finally:
        if spoken:
            with deps.pool.connection() as conn:
                messages.add_message(
                    conn,
                    turn.conversation_id,
                    "assistant",
                    "".join(spoken),
                    "hotel_options",
                    suggestions,
                )
