"""The state of a chat turn in the database: validate and save the visitor's message, read what the
handlers need, save the reply, and keep questionnaire cards and their draft in step."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from psycopg import Connection

from core.exceptions import Conflict, InvalidInput, NotFound, PlanConflict
from db.repositories import conversations, messages, research, trips
from db.repositories.messages import MessageRow
from db.repositories.research import SourceRow
from db.repositories.trips import TripRow
from domain.booking import BookingDates, dates_errors
from domain.discovery import RequestDraft
from domain.plan import Plan
from domain.questionnaire import DEFAULT_ORIGIN, answer_for
from domain.trip_request import TripRequest, today_in_vietnam
from orchestration.events import ChatEvent

if TYPE_CHECKING:
    # Imported for annotations only: orchestrator imports this module
    from orchestration.orchestrator import ChatDeps

HISTORY_MESSAGES = 10
MAX_TRIPS_IN_CONTEXT = 20
# Styles the budget step adds; answering the styles step again keeps them
BUDGET_STYLES = ("budget", "luxury")


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
    # The conversation's chosen chat model, tried first by the chat purposes
    chat_model: str | None = None
    # The visitor's current city (or Hà Nội): the origin when the message, the trip and the
    # draft name none. Never written to the draft
    default_origin: str = DEFAULT_ORIGIN


# Everything a handler may put in front of the model for one turn
@dataclass(frozen=True)
class ChatContext:
    trips: str
    trip: TripRow | None
    request: TripRequest | None
    plan: Plan | None
    sources: tuple[SourceRow, ...]
    history: tuple[MessageRow, ...]


# The assistant reply as it builds up: its intent, its metadata and the text streamed so far
@dataclass
class Reply:
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
    follow_up: FollowUp | None = None,
    today: date | None = None,
    default_origin: str | None = None,
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
        _check_follow_up(
            conn, conversation_id, follow_up, today or today_in_vietnam(datetime.now(UTC))
        )

    message = messages.add_message(conn, conversation_id, "user", content)
    conversations.touch_conversation(conn, conversation_id)
    if trip_id is not None:
        trips.touch(conn, trip_id)
    # Commit now: the call log of the stream refers to this message from other connections
    conn.commit()
    return ChatTurn(
        conversation_id,
        conversation.user_id,
        message,
        trip_id,
        plan_revision,
        follow_up,
        conversation.chat_model,
        default_origin or DEFAULT_ORIGIN,
    )


# Read the user's trips, the open trip with its plan and sources, and the recent messages
def load_context(conn: Connection[Any], turn: ChatTurn) -> ChatContext:
    lines = [
        f"- {t.destination_name} ({t.destination_country}), {t.start_date.isoformat()} to "
        f"{t.end_date.isoformat()}, {t.status}"
        for t in trips.list_trips(conn, turn.user_id, MAX_TRIPS_IN_CONTEXT, 0)
    ]
    trip = trips.get_trip(conn, turn.trip_id) if turn.trip_id else None
    plan = Plan.model_validate(trip.plan) if trip is not None and trip.plan else None
    sources = research.sources_for_trip(conn, trip.id) if trip is not None else []
    recent = messages.recent_messages(conn, turn.conversation_id, HISTORY_MESSAGES + 1)
    history = tuple(m for m in recent if m.id != turn.message.id)[-HISTORY_MESSAGES:]
    return ChatContext(
        trips="\n".join(lines),
        trip=trip,
        request=trip_request_of(trip) if trip is not None else None,
        plan=plan,
        sources=tuple(sources),
        history=history,
    )


# The request columns of a trip row as a TripRequest
def trip_request_of(row: TripRow) -> TripRequest:
    return TripRequest.model_validate(
        {
            "destination": {
                "name": row.destination_name,
                "country_code": row.destination_country,
                "lat": row.destination_lat,
                "lon": row.destination_lon,
            },
            "origin": row.origin,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "travelers": row.travelers,
            "travel_styles": row.travel_styles,
            "budget_amount": row.budget_amount,
            "budget_scope": row.budget_scope,
            "language": row.language,
            "notes": row.notes,
        }
    )


# The text the model sees for a message; a trip form or a questionnaire card becomes one line
def message_for_model(message: MessageRow) -> str:
    meta = message.metadata or {}
    if message.intent == "create_trip":
        return _trip_form_line(meta)
    if message.intent == "discover" and meta.get("kind") == "questionnaire" and not message.content:
        answers = meta.get("answers")
        known = ", ".join(sorted(answers)) if isinstance(answers, dict) and answers else "nothing"
        return f"[questionnaire: {meta.get('status', '?')}, answered {known}]"
    return message.content


# Turn the answer into draft fields, then write them into the card and the conversation's draft.
# step only grows, so answering an earlier step again leaves it where it was
def answer_questionnaire(
    conn: Connection[Any],
    conversation_id: UUID,
    message_id: UUID,
    step: int,
    choice: str | list[str] | None,
    typed: Mapping[str, Any],
    today: date,
) -> MessageRow:
    # Locked so two answers sent at once cannot both start from the same card and draft
    card = messages.get_message(conn, message_id, lock=True)
    if card.conversation_id != conversation_id:
        raise NotFound(f"message {message_id}")
    meta = card.metadata or {}
    if card.intent != "discover" or meta.get("kind") != "questionnaire":
        raise Conflict(f"message {message_id} is not a questionnaire")
    if meta.get("status") != "open":
        raise Conflict(f"questionnaire {message_id} is already closed")
    try:
        fields = answer_for(step, choice, typed, today)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc

    draft = conversations.get_conversation(conn, conversation_id).request_draft or {}
    old_styles = draft.get("travel_styles") or []
    if "travel_styles" in fields or (step == 3 and fields):
        styles = _styles(old_styles, fields, step)
        if "travel_styles" in fields or styles != old_styles:
            fields["travel_styles"] = styles
    answers = RequestDraft.model_validate(fields).model_dump(mode="json", include=set(fields))
    metadata = {
        **meta,
        "step": max(int(meta.get("step", 0)), step),
        "answers": {**meta.get("answers", {}), **answers},
        "choices": {**meta.get("choices", {}), str(step): choice},
    }
    saved = messages.update_open_metadata(conn, message_id, {"status": "open"}, metadata)
    if saved is None:
        raise Conflict(f"questionnaire {message_id} is already closed")
    conversations.save_draft(conn, conversation_id, {**draft, **answers})
    return saved


# Save the assistant message with the text streamed so far; nothing is saved without an intent
# or text
def save_reply(reply: Reply, turn: ChatTurn, deps: ChatDeps) -> None:
    text = "".join(reply.parts)
    if reply.intent and text:
        with deps.pool.connection() as conn:
            messages.add_message(
                conn, turn.conversation_id, "assistant", text, reply.intent, reply.metadata
            )


# prepare_message closed the card; when the turn fails or is closed before its first token, open
# the card again so the visitor can press it once more
def reopen_on_failure(
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


# The card must be this conversation's and still waiting; chosen dates must keep the rules. Then
# close it, locked, so a second press gets 409 before its message is saved
def _check_follow_up(
    conn: Connection[Any],
    conversation_id: UUID,
    follow_up: FollowUp,
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
    if errors:
        raise InvalidInput("; ".join(errors))
    done = {**meta, "status": "done"}
    messages.update_open_metadata(conn, card.id, {"status": "need_dates"}, done)


# "[trip form: place, when, status]"; a draft that is not an object gives a bare marker
def _trip_form_line(meta: dict[str, Any]) -> str:
    form = meta.get("draft")
    if not isinstance(form, dict):
        return "[trip form]"
    destination = form.get("destination")
    place = destination.get("name") if isinstance(destination, dict) else None
    if form.get("start_date") and form.get("end_date"):
        when = f"{form['start_date']} to {form['end_date']}"
    elif form.get("length_days"):
        when = f"{form['length_days']} days"
    else:
        when = "no dates"
    return f"[trip form: {place or '?'}, {when}, {meta.get('status', '?')}]"


# The styles step replaces the chosen styles but keeps a budget style; the budget step swaps the
# budget style for its own (or none)
def _styles(old: list[str], fields: Mapping[str, Any], step: int) -> list[str]:
    new = list(fields.get("travel_styles", []))
    if step == 1:
        return [*new, *(s for s in old if s in BUDGET_STYLES and s not in new)]
    kept = [s for s in old if s not in BUDGET_STYLES]
    return list(dict.fromkeys([*kept, *new]))
