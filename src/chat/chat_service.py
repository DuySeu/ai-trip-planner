"""One chat turn: validate the message, classify it, run the handler, stream the reply."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg_pool import ConnectionPool

from agents.orchestrator_agent import OrchestratorAgent
from chat.booking_turn import run_booking_follow_up, run_booking_turn
from chat.create_trip_turn import run_create_trip_turn
from chat.discovery_turn import run_discover_turn, run_suggest_turn
from chat.events import REPLY_ERRORS, ChatEvent, event_for_error, token_events
from chat.handlers import (
    ChatContext,
    answer_about_plan,
    answer_from_research,
    edit_plan,
    give_travel_advice,
    load_context,
)
from chat.history import message_for_model
from core.exceptions import Conflict, InvalidInput, NotFound, PlanConflict
from core.settings import Settings
from db.repositories import conversations, messages, trips
from db.repositories.messages import MessageRow
from domain.booking import BookingDates, BookingKind, dates_errors
from domain.trip_request import Language, today_in_vietnam
from models.model_router import CallContext, ModelRouter, RouterProvider
from orchestration.routing_schema import AgentSpec, RoutingDecision
from research.places import Place
from service.tavily.search import WebSearch

logger = logging.getLogger(__name__)

# The agents the classifier may route to, with the descriptions it sees
CATALOG: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="advice",
        description="Answer a travel question from what is known: a question about the plan of "
        "the open trip, or general advice and tips (what to pack, which area to stay in, how to "
        "get around, is a month good for a place). Also questions asked while thinking about a "
        'trip, such as "I want 3 days in Hai Phong, which area is good?". No web search.',
    ),
    AgentSpec(
        name="web_lookup",
        description="A question that needs new, current facts from the web that general "
        'knowledge and the plan do not hold, such as "what festivals are on in Da Nang in '
        'July?" or visa rules this year. Not for hotels or flights (hotel_search and '
        "flight_search do those) and not for a question about the open plan. The step task is "
        "the web search query.",
    ),
    AgentSpec(
        name="discover",
        description="The visitor wants ideas for WHERE to go on a new trip, or says they want "
        'to travel but has no destination yet, such as "I want a beach trip" or "gợi ý chỗ đi '
        'chơi cuối tuần". Also "give me other ideas".',
    ),
    AgentSpec(
        name="hotel_search",
        description="Find hotels or places to stay in a named place, or what they cost per "
        'night, such as "4-star hotels in Hai Phong" or "khách sạn gần biển Đồ Sơn giá rẻ". '
        "The step task is a web search query for those hotels with the place, the stars or "
        "budget and the word price.",
    ),
    AgentSpec(
        name="flight_search",
        description="Find flights, trains or buses between two places, or what a ticket costs, "
        'such as "vé máy bay Hà Nội đi Đà Nẵng" or "train from Hanoi to Hue". The step task '
        "is a web search query with the origin, the destination, the mode and the word price.",
    ),
    AgentSpec(
        name="create_trip",
        description="Only when the visitor directly asks the app to make the day-by-day plan "
        'or itinerary of a new trip now, such as "make the plan for me" or "tạo plan trip cho '
        'tôi", or answers yes ("có", "ok", "yes") right after the assistant asked whether to '
        "make the plan. Asking a question while planning a trip is advice, not this. Not to "
        "change the open trip.",
    ),
    AgentSpec(
        name="edit_plan",
        description="Change the plan of the open trip: add, move, replace or remove things, "
        "or change its dates, number of travelers, origin or language.",
    ),
)
# The intent saved for each agent; an agent the catalog does not have is advice
AGENT_INTENT: Mapping[str, str] = {
    "advice": "advice",
    "web_lookup": "advice",
    "discover": "discover",
    "hotel_search": "booking_search",
    "flight_search": "booking_search",
    "create_trip": "create_trip",
    "edit_plan": "edit_plan",
}


# What a chat turn needs from the outside; the API builds it once and shares it
@dataclass(frozen=True)
class ChatDeps:
    pool: ConnectionPool
    router: ModelRouter
    search: WebSearch
    settings: Settings
    now: Callable[[], datetime]
    places: Callable[[str, Language], list[Place]]


# A message that answers a card instead of going through the router: suggest from a questionnaire
# card, or search with the dates chosen on a booking card
@dataclass(frozen=True)
class FollowUp:
    message_id: UUID
    kind: Literal["discover", "booking"]
    dates: BookingDates | None = None
    origin: str | None = None


# A validated message: the saved user message and what the visitor had open
@dataclass(frozen=True)
class ChatTurn:
    conversation_id: UUID
    user_id: UUID
    message: MessageRow
    trip_id: UUID | None
    plan_revision: int | None
    follow_up: FollowUp | None = None


# The assistant reply as it builds up: its intent, its metadata and the text streamed so far
@dataclass
class _Reply:
    intent: str | None = None
    metadata: dict[str, Any] | None = None
    parts: list[str] = field(default_factory=list)


# Check the message against the conversation and the open trip, close the card a follow-up comes
# from, then save it; nothing streams yet
def prepare_message(
    conn: Connection[Any],
    conversation_id: UUID,
    content: str,
    trip_id: UUID | None,
    plan_revision: int | None,
    retention_days: int = 30,
    follow_up: FollowUp | None = None,
    today: date | None = None,
) -> ChatTurn:
    conversation = conversations.get_conversation(conn, conversation_id)
    trip = None
    if trip_id is not None:
        trip = trips.get_trip(conn, trip_id)
        if trip.user_id != conversation.user_id:
            raise NotFound(f"trip {trip_id}")
        if plan_revision is not None and plan_revision != trip.plan_revision:
            raise PlanConflict(f"trip {trip_id} is at revision {trip.plan_revision}")
        if trip.plan is None:
            raise Conflict(f"trip {trip_id} has no plan yet")
    if follow_up is not None:
        origin = (
            trip.origin if trip is not None else (conversation.request_draft or {}).get("origin")
        )
        _check_follow_up(
            conn, conversation_id, follow_up, origin, today or today_in_vietnam(datetime.now(UTC))
        )

    message = messages.add_message(conn, conversation_id, "user", content)
    conversations.touch_conversation(conn, conversation_id)
    if trip_id is not None:
        trips.touch(conn, trip_id, retention_days)
    # Commit now: the call log of the stream refers to this message from other connections
    conn.commit()
    return ChatTurn(
        conversation_id, conversation.user_id, message, trip_id, plan_revision, follow_up
    )


# The card must be this conversation's and still waiting; chosen dates must keep the rules. Then
# close it, locked, so a second press gets 409 before its message is saved
def _check_follow_up(
    conn: Connection[Any],
    conversation_id: UUID,
    follow_up: FollowUp,
    known_origin: str | None,
    today: date,
) -> None:
    card = messages.get_message(conn, follow_up.message_id, lock=True)
    if card.conversation_id != conversation_id:
        raise NotFound(f"message {follow_up.message_id}")
    meta = card.metadata or {}
    if follow_up.kind == "discover":
        if card.intent != "discover" or meta.get("kind") != "questionnaire":
            raise Conflict(f"message {card.id} is not a questionnaire")
        if meta.get("status") != "open":
            raise Conflict(f"questionnaire {card.id} is already closed")
        messages.update_open_metadata(conn, card.id, {"status": "open"}, {**meta, "status": "done"})
        return
    if card.intent != "booking_search" or meta.get("status") != "need_dates":
        raise Conflict(f"message {card.id} is not waiting for dates")
    errors = dates_errors(meta["kind"], follow_up.dates or BookingDates(), today)
    if meta["kind"] == "flight" and not (follow_up.origin or known_origin):
        errors.append("origin is required")
    if errors:
        raise InvalidInput("; ".join(errors))
    done = {**meta, "status": "done"}
    messages.update_open_metadata(conn, card.id, {"status": "need_dates"}, done)


# Stream the reply: tokens, a plan or metadata event, then done. The assistant message is
# saved with the text sent so far when the stream ends, fails or is closed by the client.
def stream_reply(turn: ChatTurn, deps: ChatDeps) -> Iterator[ChatEvent]:
    reply = _Reply()
    try:
        for event in _dispatch(turn, deps, reply):
            if event.type == "token":
                reply.parts.append(event.data["text"])
            yield event
    except REPLY_ERRORS as exc:
        yield event_for_error(exc)
    finally:
        text = "".join(reply.parts)
        if reply.intent and text:
            with deps.pool.connection() as conn:
                messages.add_message(
                    conn, turn.conversation_id, "assistant", text, reply.intent, reply.metadata
                )
    yield ChatEvent("done", {})


# Classify the message and run the handler of its intent
def _dispatch(turn: ChatTurn, deps: ChatDeps, reply: _Reply) -> Iterator[ChatEvent]:
    call_ctx = CallContext(
        trip_id=turn.trip_id, conversation_id=turn.conversation_id, message_id=turn.message.id
    )
    with deps.pool.connection() as conn:
        data = load_context(conn, turn)
    if turn.follow_up is not None:
        # The card's id says what to run; these turns save their own assistant message
        if turn.follow_up.kind == "discover":
            follow = run_suggest_turn(turn, deps, call_ctx)
        else:
            follow = run_booking_follow_up(data, turn, deps, call_ctx)
        yield from _reopen_on_failure(follow, turn.follow_up, deps)
        return
    decision = _classify(data, turn, deps, call_ctx)

    if decision.status == "needs_clarification":
        reply.intent, reply.metadata = "advice", {"clarify": True}
        yield from token_events(decision.clarification or "")
        return

    # ponytail: only the first step runs; a multi-step decision is cut to its first agent
    step = decision.steps[0] if decision.status == "routed" else None
    picked = step.agent if step is not None else "none"
    agent = picked if picked in AGENT_INTENT else "advice"
    task = step.task.strip() if step is not None and step.task.strip() else turn.message.content
    logger.info(
        "chat flow: %s (classifier picked %s, %s): %s",
        agent,
        picked,
        decision.status,
        decision.reasoning,
    )

    # These turns save their own assistant message
    if agent == "discover":
        yield from run_discover_turn(turn, deps, call_ctx)
        return
    if agent == "create_trip":
        yield from run_create_trip_turn(turn, deps)
        return
    if agent in ("hotel_search", "flight_search"):
        kind: BookingKind = "hotel" if agent == "hotel_search" else "flight"
        yield from run_booking_turn(data, turn, deps, call_ctx, kind, task)
        return

    reply.intent = AGENT_INTENT[agent]
    match agent:
        case "edit_plan":
            yield from edit_plan(data, turn, deps, call_ctx)
        case "web_lookup":
            reply.metadata = {"searched": True}
            yield from answer_from_research(data, turn, deps, call_ctx, task)
        case _ if data.plan is not None:
            yield from answer_about_plan(data, turn, deps, call_ctx)
        case _:
            yield from give_travel_advice(data, turn, deps, call_ctx)


# prepare_message closed the card; when the turn fails or is closed before its first token, open
# the card again so the visitor can press it once more
def _reopen_on_failure(
    events: Iterator[ChatEvent], follow_up: FollowUp, deps: ChatDeps
) -> Iterator[ChatEvent]:
    started = False
    try:
        for event in events:
            started = started or event.type == "token"
            yield event
    except BaseException:
        if not started:
            waiting = "open" if follow_up.kind == "discover" else "need_dates"
            with deps.pool.connection() as conn:
                card = messages.get_message(conn, follow_up.message_id)
                meta = {**(card.metadata or {}), "status": waiting}
                messages.update_open_metadata(conn, card.id, {"status": "done"}, meta)
        raise


# Ask the classifier where the message goes, with the last messages as history
def _classify(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> RoutingDecision:
    provider = RouterProvider(deps.router, "classify", call_ctx)
    agent = OrchestratorAgent(model_id=provider.model_id, inference_config={}, llm=provider)
    history = [{"role": m.role, "content": message_for_model(m)} for m in data.history]
    return agent.route([*history, {"role": "user", "content": turn.message.content}], CATALOG)
