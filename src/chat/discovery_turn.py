"""Help a visitor who does not know where to go: ask, suggest destination cards, or answer.

The orchestrator picks the action; each action costs one LLM call."""

from __future__ import annotations

import calendar
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from agents.discover_answer_agent import DiscoverAnswerAgent
from agents.discover_ask_agent import DiscoverAskAgent
from agents.discover_suggest_agent import DiscoverSuggestAgent
from chat.events import ChatEvent, token_events
from chat.handlers import HISTORY_MESSAGES, VIETNAMESE_LETTER, conversation_text, sources_text
from core.exceptions import ResearchFailed
from db.repositories import conversations, messages, research
from db.repositories.research import SourceInput
from domain.discovery import DiscoveryReply, RequestDraft, merge_draft
from domain.trip_request import Language
from models.model_router import CallContext
from research.queries import STYLES_VI
from service.tavily.search import SearchHit

if TYPE_CHECKING:
    # Imported for annotations only: chat_service imports this module
    from chat.chat_service import ChatDeps, ChatTurn

logger = logging.getLogger(__name__)

MAX_ASKS = 2
MAX_QUERIES = 3
Action = Literal["ask", "suggest", "answer"]


# Web search queries from the draft, in Vietnamese or English, for when the model gave none
def discovery_queries(draft: RequestDraft, language: Language) -> tuple[str, ...]:
    month = draft.start_date.month if draft.start_date else None
    if month is None and draft.month:
        names = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}
        month = names.get(draft.month.strip().lower())

    if language == "vi":
        style = ", ".join(STYLES_VI[s] for s in draft.travel_styles)
        when = f"tháng {month}" if month else ""
        origin = f"từ {draft.origin}" if draft.origin else ""
        days = f"{draft.length_days} ngày" if draft.length_days else ""
        raw = (
            f"địa điểm du lịch {style} đẹp {when} {origin}",
            f"du lịch {days} {style} giá rẻ {when} {origin}",
            f"nên đi đâu {when} {origin} {style}",
        )
    else:
        style = " and ".join(draft.travel_styles)
        when = f"in {calendar.month_name[month]}" if month else ""
        origin = f"from {draft.origin}" if draft.origin else ""
        days = f"{draft.length_days}-day" if draft.length_days else ""
        raw = (
            f"best {style} travel destinations {when} {origin}",
            f"affordable {days} {style} trip ideas {when} {origin}",
            f"where to go {when} {origin} {style} holiday",
        )
    return tuple(" ".join(q.split()) for q in raw)


# Run one discovery turn for a saved user message; the assistant message is saved when the stream ends.
# After MAX_ASKS questions an "ask" becomes a "suggest". The draft is saved before any text is streamed.
def run_discovery_turn(
    turn: ChatTurn, deps: ChatDeps, action: Action, query: str | None = None
) -> Iterator[ChatEvent]:
    call_ctx = CallContext(
        trip_id=turn.trip_id, conversation_id=turn.conversation_id, message_id=turn.message.id
    )
    message = turn.message.content
    with deps.pool.connection() as conn:
        conversation = conversations.get_conversation(conn, turn.conversation_id)
        recent = messages.recent_messages(conn, turn.conversation_id, HISTORY_MESSAGES + 1)
        asks = messages.count_intent(conn, turn.conversation_id, "ask")
    history = tuple(m for m in recent if m.id != turn.message.id)[-HISTORY_MESSAGES:]
    known = conversation.request_draft or {}
    if action == "ask" and asks >= MAX_ASKS:
        action = "suggest"

    today = deps.now().date()
    conversation_block = conversation_text(history)
    spoken: list[str] = []
    suggestions: list[dict[str, Any]] | None = None
    try:
        decided: DiscoveryReply
        if action == "suggest":
            # Search first, so the one model call can write the reply and the cards from the hits
            draft_now = RequestDraft.model_validate(known)
            language: Language = draft_now.language or (
                "vi" if VIETNAMESE_LETTER.search(message) else "en"
            )
            planned = [query.strip()] if query and query.strip() else []
            queries = tuple(dict.fromkeys([*planned, *discovery_queries(draft_now, language)]))
            hits = _search(deps, queries[:MAX_QUERIES])
            with deps.pool.connection() as conn:
                saved = research.save_sources(
                    conn,
                    conversation_id=turn.conversation_id,
                    kind="chat",
                    items=[SourceInput(h.title, h.url, h.content) for h in hits],
                )
            result = DiscoverSuggestAgent(deps.router).run(
                known,
                today,
                conversation_block,
                sources_text(saved),
                frozenset(s.id for s in saved),
                message,
                call_ctx,
            )
            decided = result
            suggestions = [c.model_dump(mode="json") for c in result.cards]
        elif action == "ask":
            decided = DiscoverAskAgent(deps.router).run(
                known, today, conversation_block, message, call_ctx
            )
        else:
            decided = DiscoverAnswerAgent(deps.router).run(
                known, today, conversation_block, message, call_ctx
            )

        # Save the draft, then stream
        with deps.pool.connection() as conn:
            conversations.save_draft(
                conn, turn.conversation_id, merge_draft(known, decided.request_draft)
            )
        for event in token_events(decided.reply):
            spoken.append(event.data["text"])
            yield event
        if suggestions is not None:
            yield ChatEvent("suggestions", {"cards": suggestions})
    finally:
        if spoken:
            with deps.pool.connection() as conn:
                messages.add_message(
                    conn, turn.conversation_id, "assistant", "".join(spoken), action, suggestions
                )


# Search each query; a failed search is skipped, a repeated url is kept once
def _search(deps: ChatDeps, queries: tuple[str, ...]) -> list[SearchHit]:
    hits: dict[str, SearchHit] = {}
    for query in queries:
        try:
            found = deps.search(query, "discovery")
        except ResearchFailed as exc:
            logger.warning("discovery search failed: %s", exc)
            continue
        for hit in found:
            hits.setdefault(hit.url, hit)
    return list(hits.values())
