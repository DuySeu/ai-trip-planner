"""Help a visitor who does not know where to go: a questionnaire card, then destination suggestions.

The router picks ``discover`` once; the card's answers come back through PATCH, and the visitor asks
for suggestions with ``POST /chat`` and the card's id, which skips the router."""

from __future__ import annotations

import calendar
import logging
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from agents.create_trip_agent import CreateTripAgent, drop_past_dates
from agents.discover_suggest_agent import DiscoverSuggestAgent
from chat.events import ChatEvent, metadata_event, token_events
from chat.handlers import HISTORY_MESSAGES, VIETNAMESE_LETTER, conversation_text, sources_text
from core.exceptions import Conflict, InvalidLLMOutput, LLMUnavailable, ResearchFailed
from db.repositories import conversations, messages, research
from db.repositories.research import SourceInput
from domain.discovery import RequestDraft, TripFormExtract, merge_draft
from domain.questionnaire import first_missing_step, questionnaire_metadata
from domain.trip_request import Language, today_in_vietnam
from models.model_router import CallContext
from research.queries import STYLES_VI
from service.tavily.search import SearchHit

if TYPE_CHECKING:
    # Imported for annotations only: chat_service imports this module
    from chat.chat_service import ChatDeps, ChatTurn

logger = logging.getLogger(__name__)

MAX_QUERIES = 3


# Web search queries from the draft, in Vietnamese or English
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
    return tuple(dict.fromkeys(" ".join(q.split()) for q in raw))


# The router picked discover: read the message into the draft, then suggest when the draft answers
# every question or a card is already open (the visitor typed instead of pressing it); else save a
# questionnaire card that starts at the first unanswered question
def run_discover_turn(turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext) -> Iterator[ChatEvent]:
    with deps.pool.connection() as conn:
        conversation = conversations.get_conversation(conn, turn.conversation_id)
        recent = messages.recent_messages(conn, turn.conversation_id, HISTORY_MESSAGES + 1)
    history = tuple(m for m in recent if m.id != turn.message.id)[-HISTORY_MESSAGES:]
    known = conversation.request_draft or {}

    # A model that fails leaves the draft as it was; the card still opens
    today = today_in_vietnam(deps.now())
    try:
        extract = CreateTripAgent(deps.router).run(
            known, today, conversation_text(history), turn.message.content, call_ctx
        )
    except (InvalidLLMOutput, LLMUnavailable) as exc:
        logger.warning("discover extract failed: %s", exc)
        extract = TripFormExtract()
    learned = RequestDraft.model_validate(
        drop_past_dates(extract, today).model_dump(exclude={"destination", "destination_name"})
    )
    draft = merge_draft(known, learned)

    with deps.pool.connection() as conn:
        conversations.save_draft(conn, turn.conversation_id, draft)
        card = messages.find_open_questionnaire(conn, turn.conversation_id)
        if card is not None:
            _close(conn, card.id, card.metadata or {})
        elif first_missing_step(draft) is not None:
            metadata = questionnaire_metadata(draft)
            card = messages.add_message(
                conn, turn.conversation_id, "assistant", "", "discover", metadata
            )
            logger.info("discover: questionnaire card %s at step %d", card.id, metadata["step"])
            yield metadata_event(card.id, metadata)
            return
    yield from _suggest(turn, deps, call_ctx, draft)


# The visitor pressed suggest on the card (prepare_message closed it): suggest from the draft as it is
def run_suggest_turn(turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext) -> Iterator[ChatEvent]:
    with deps.pool.connection() as conn:
        draft = conversations.get_conversation(conn, turn.conversation_id).request_draft or {}
    yield from _suggest(turn, deps, call_ctx, draft)


# Mark an open questionnaire card done; Conflict when another request closed it first
def _close(conn: Any, card_id: Any, metadata: Mapping[str, Any]) -> None:
    done = {**metadata, "status": "done"}
    if messages.update_open_metadata(conn, card_id, {"status": "open"}, done) is None:
        raise Conflict(f"questionnaire {card_id} is already closed")


# Search with queries made from the draft, ask the model once for the reply and the cards, stream
# the reply, then send the cards; the message is saved when the stream ends, fails or is closed
def _suggest(
    turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext, known: Mapping[str, Any]
) -> Iterator[ChatEvent]:
    message = turn.message.content
    with deps.pool.connection() as conn:
        recent = messages.recent_messages(conn, turn.conversation_id, HISTORY_MESSAGES + 1)
    history = tuple(m for m in recent if m.id != turn.message.id)[-HISTORY_MESSAGES:]

    draft_now = RequestDraft.model_validate(known)
    language: Language = draft_now.language or ("vi" if VIETNAMESE_LETTER.search(message) else "en")
    hits = _search(deps, discovery_queries(draft_now, language)[:MAX_QUERIES])
    with deps.pool.connection() as conn:
        saved = research.save_sources(
            conn,
            conversation_id=turn.conversation_id,
            kind="chat",
            items=[SourceInput(h.title, h.url, h.content) for h in hits],
        )
    result = DiscoverSuggestAgent(deps.router).run(
        known,
        today_in_vietnam(deps.now()),
        conversation_text(history),
        sources_text(saved),
        frozenset(s.id for s in saved),
        message,
        call_ctx,
    )
    with deps.pool.connection() as conn:
        conversations.save_draft(
            conn, turn.conversation_id, merge_draft(known, result.request_draft)
        )

    metadata: dict[str, Any] = {"kind": "suggestions", "cards": []}
    spoken: list[str] = []
    try:
        for event in token_events(result.reply):
            spoken.append(event.data["text"])
            yield event
        metadata["cards"] = [c.model_dump(mode="json") for c in result.cards]
        yield metadata_event(None, metadata)
    finally:
        if spoken:
            with deps.pool.connection() as conn:
                messages.add_message(
                    conn, turn.conversation_id, "assistant", "".join(spoken), "discover", metadata
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
