"""A visitor who wants to plan a trip now gets a form prefilled from the chat.

One LLM call reads the chat; code finds the destination's coordinates. The form is one assistant
message (intent ``trip_form``) whose content is the draft as JSON; no text is streamed."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from agents.create_trip_agent import CreateTripAgent, drop_past_dates
from chat.events import ChatEvent
from chat.handlers import HISTORY_MESSAGES, VIETNAMESE_LETTER, conversation_text
from core.exceptions import InvalidLLMOutput, LLMUnavailable, ResearchFailed
from db.repositories import conversations, messages
from domain.discovery import RequestDraft, TripFormExtract, merge_draft
from domain.trip_request import Destination, Language, today_in_vietnam
from models.model_router import CallContext

if TYPE_CHECKING:
    # Imported for annotations only: chat_service imports this module
    from chat.chat_service import ChatDeps, ChatTurn

logger = logging.getLogger(__name__)


# Save a trip form message and the draft it shows, then emit one trip_form event.
# Running out of AI quota ends the turn with an error; any other model failure still gives a form.
def run_create_trip_turn(turn: ChatTurn, deps: ChatDeps) -> Iterator[ChatEvent]:
    call_ctx = CallContext(
        trip_id=turn.trip_id, conversation_id=turn.conversation_id, message_id=turn.message.id
    )
    message = turn.message.content
    with deps.pool.connection() as conn:
        conversation = conversations.get_conversation(conn, turn.conversation_id)
        recent = messages.recent_messages(conn, turn.conversation_id, HISTORY_MESSAGES + 1)
    history = tuple(m for m in recent if m.id != turn.message.id)[-HISTORY_MESSAGES:]
    known = conversation.request_draft or {}

    # Read the chat; a model that fails leaves the form to the old draft and the defaults
    today = today_in_vietnam(deps.now())
    try:
        extract = CreateTripAgent(deps.router).run(
            known, today, conversation_text(history), message, call_ctx
        )
    except (InvalidLLMOutput, LLMUnavailable) as exc:
        logger.warning("create trip extract failed: %s", exc)
        extract = TripFormExtract()
    extract = drop_past_dates(extract, today)

    # The model only names the destination; the coordinates come from the place search
    destination: Destination | None = None
    if extract.destination_name:
        language: Language = "vi" if VIETNAMESE_LETTER.search(message) else "en"
        try:
            found = deps.places(extract.destination_name, language)
        except ResearchFailed as exc:
            logger.warning("create trip place search failed: %s", exc)
            found = []
        if found:
            place = found[0]
            destination = Destination(
                name=place.name, country_code=place.country_code, lat=place.lat, lon=place.lon
            )

    # Merge into the saved draft, without any destination the model wrote itself
    learned = RequestDraft.model_validate(
        extract.model_dump(exclude={"destination", "destination_name"})
    )
    draft = merge_draft(known, learned)
    if destination is not None:
        draft["destination"] = destination.model_dump(mode="json")

    with deps.pool.connection() as conn:
        conversations.save_draft(conn, turn.conversation_id, draft)
        form = messages.add_message(
            conn,
            turn.conversation_id,
            "assistant",
            json.dumps(draft, ensure_ascii=False),
            "trip_form",
        )
    logger.info(
        "trip form %s: model named %r, place found %s, fields %s",
        form.id,
        extract.destination_name,
        f"{destination.name} ({destination.country_code})" if destination else "none",
        ", ".join(sorted(draft)) or "none",
    )
    yield ChatEvent("trip_form", {"message_id": str(form.id), "draft": draft})
