"""A hotel or ticket search needs dates: search when they are known, else save a card asking for them.

The card is a ``booking_search`` message with status ``need_dates``; the visitor's chosen dates come
back through ``POST /chat`` with the card's id and skip the router. Results go out as one
``metadata`` event and are saved in the message's metadata, so they come back on reload."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from agents.flight_options_agent import FlightOptionsAgent
from agents.hotel_options_agent import HotelOptionsAgent
from chat.events import ChatEvent, metadata_event, token_events
from chat.handlers import ChatContext, build_prompt, localized, sources_text
from core.exceptions import ResearchFailed
from db.repositories import conversations, messages, research
from db.repositories.research import SourceInput, SourceRow
from domain.booking import BookingDates, BookingKind, dates_errors, dates_from
from domain.flights import flight_cards_out
from domain.hotels import hotel_cards_out
from domain.trip_request import today_in_vietnam
from models.model_router import CallContext

if TYPE_CHECKING:
    # Imported for annotations only: chat_service imports this module
    from chat.chat_service import ChatDeps, ChatTurn

logger = logging.getLogger(__name__)

# The card's question, as (English, Vietnamese)
ASK_DATES: dict[BookingKind, tuple[str, str]] = {
    "hotel": ("Which dates do you want to stay?", "Bạn định nhận phòng và trả phòng ngày nào?"),
    "flight": ("When do you want to travel?", "Bạn định đi ngày nào?"),
}
# The search task and the research kind of each search
SEARCH_TASK: dict[BookingKind, Any] = {"hotel": "accommodation", "flight": "transport"}


# Search when the open trip or the draft gives dates that still keep the rules (and, for tickets, the
# origin); else save a need_dates card and send it in one metadata event
def run_booking_turn(
    data: ChatContext,
    turn: ChatTurn,
    deps: ChatDeps,
    call_ctx: CallContext,
    kind: BookingKind,
    query: str,
) -> Iterator[ChatEvent]:
    with deps.pool.connection() as conn:
        draft = conversations.get_conversation(conn, turn.conversation_id).request_draft or {}
    dates = dates_from(kind, draft, data.request)
    origin = data.request.origin if data.request is not None else draft.get("origin")
    today = today_in_vietnam(deps.now())
    if dates is None or dates_errors(kind, dates, today) or (kind == "flight" and not origin):
        yield from _ask_dates(turn, deps, kind, query)
        return
    yield from _search(data, turn, deps, call_ctx, kind, query, dates, origin)


# The visitor chose dates on a card (checked and closed by prepare_message): keep the dates (and
# origin) in the draft when it has none, then run the search the card was waiting for
def run_booking_follow_up(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> Iterator[ChatEvent]:
    follow_up = turn.follow_up
    assert follow_up is not None and follow_up.dates is not None
    dates = follow_up.dates
    with deps.pool.connection() as conn:
        card = messages.get_message(conn, follow_up.message_id)
        meta = card.metadata or {}
        draft = conversations.get_conversation(conn, turn.conversation_id).request_draft or {}
        kind: BookingKind = meta["kind"]
        start, end = (
            (dates.check_in, dates.check_out) if kind == "hotel" else (dates.depart, dates.return_)
        )
        learned: dict[str, Any] = {}
        if not draft.get("start_date") and start is not None:
            learned = {"start_date": start.isoformat()}
            if end is not None:
                learned["end_date"] = end.isoformat()
        if follow_up.origin and not draft.get("origin"):
            learned["origin"] = follow_up.origin
        if learned:
            conversations.save_draft(conn, turn.conversation_id, {**draft, **learned})
    known_origin = data.request.origin if data.request is not None else draft.get("origin")
    origin = follow_up.origin or known_origin
    yield from _search(data, turn, deps, call_ctx, kind, meta["query"], dates, origin)


# Search the booking or ticket sites with the month, ask the model once with the dates, stream the
# reply, then send the cards; the message is saved when the stream ends, fails or is closed, with
# the cards only when the reply was sent whole
def _search(
    data: ChatContext,
    turn: ChatTurn,
    deps: ChatDeps,
    call_ctx: CallContext,
    kind: BookingKind,
    query: str,
    dates: BookingDates,
    origin: str | None,
) -> Iterator[ChatEvent]:
    if kind == "hotel":
        assert dates.check_in is not None and dates.check_out is not None
        month = dates.check_in
        when = f"check-in {dates.check_in.isoformat()}, check-out {dates.check_out.isoformat()}"
        shown = dates.model_dump(mode="json", include={"check_in", "check_out"})
    else:
        assert dates.depart is not None
        month = dates.depart
        back = f", return {dates.return_.isoformat()}" if dates.return_ else ""
        when = f"depart {dates.depart.isoformat()}{back}, from {origin}"
        shown = dates.model_dump(mode="json", include={"depart", "return_"}, by_alias=True)

    task = SEARCH_TASK[kind]
    try:
        hits = deps.search(f"{query} {month:%m/%Y}", task)
    except ResearchFailed as exc:
        logger.warning("%s search failed: %s", kind, exc)
        hits = []
    saved: list[SourceRow] = []
    if hits:
        with deps.pool.connection() as conn:
            saved = research.save_sources(
                conn,
                trip_id=turn.trip_id,
                conversation_id=None if turn.trip_id else turn.conversation_id,
                kind=task,
                items=[SourceInput(h.title, h.url, h.content) for h in hits],
            )

    content = build_prompt(
        data, f"{turn.message.content}\n({when})", search_results=sources_text(saved)
    )
    urls = {s.id: s.url for s in saved if s.url}
    if kind == "hotel":
        hotel = HotelOptionsAgent(deps.router).run(content, call_ctx)
        reply, written, cards = hotel.reply, len(hotel.cards), hotel_cards_out(hotel.cards, urls)
    else:
        flight = FlightOptionsAgent(deps.router).run(content, call_ctx)
        reply, written = flight.reply, len(flight.cards)
        cards = flight_cards_out(flight.cards, urls)
    logger.info(
        "%s options: %d results, model wrote %d cards, %d kept",
        kind,
        len(hits),
        written,
        len(cards),
    )

    metadata: dict[str, Any] = {
        "kind": kind,
        "status": "results",
        "query": query,
        "dates": shown,
        "cards": [],
    }
    spoken: list[str] = []
    try:
        for event in token_events(reply):
            spoken.append(event.data["text"])
            yield event
        metadata["cards"] = cards
        yield metadata_event(None, metadata)
    finally:
        if spoken:
            with deps.pool.connection() as conn:
                messages.add_message(
                    conn,
                    turn.conversation_id,
                    "assistant",
                    "".join(spoken),
                    "booking_search",
                    metadata,
                )


# Save the card asking for dates, then send its question and the card with its id
def _ask_dates(
    turn: ChatTurn, deps: ChatDeps, kind: BookingKind, query: str
) -> Iterator[ChatEvent]:
    metadata = {"kind": kind, "status": "need_dates", "query": query}
    text = localized(turn.message.content, ASK_DATES[kind])
    with deps.pool.connection() as conn:
        card = messages.add_message(
            conn, turn.conversation_id, "assistant", text, "booking_search", metadata
        )
    logger.info("booking search %s: no dates yet, card %s", kind, card.id)
    yield from token_events(text)
    yield metadata_event(card.id, metadata)
