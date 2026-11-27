"""Events of a chat reply stream and their server-sent-events form."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from core.exceptions import (
    Conflict,
    InvalidLLMOutput,
    LLMBudgetExceeded,
    LLMUnavailable,
    NotFound,
    QuotaExhausted,
)

EventType = Literal["token", "plan", "metadata", "error", "done"]
WORD_END = re.compile(r"(?<= )")
# Errors a reply can end with; each becomes an error event instead of a broken stream
REPLY_ERRORS = (
    QuotaExhausted,
    LLMUnavailable,
    LLMBudgetExceeded,
    InvalidLLMOutput,
    Conflict,
    NotFound,
)


# One event of the reply stream; data is the JSON body the frontend reads
@dataclass(frozen=True)
class ChatEvent:
    type: EventType
    data: dict[str, Any]


# The event in server-sent-events wire form
def to_sse(event: ChatEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


# An error event with the code the frontend switches on
def error_event(code: str, message: str, **extra: Any) -> ChatEvent:
    return ChatEvent("error", {"code": code, "message": message, **extra})


# The structured part of a reply (cards, a form, a card's state); message_id is set when the
# message was saved before the event, null when it is saved after the stream
def metadata_event(message_id: UUID | None, metadata: Mapping[str, Any]) -> ChatEvent:
    data = {
        "message_id": None if message_id is None else str(message_id),
        "metadata": dict(metadata),
    }
    return ChatEvent("metadata", data)


# The text as token events, one per word, so the frontend can show it as it arrives
def token_events(text: str) -> Iterator[ChatEvent]:
    for piece in WORD_END.split(text):
        if piece:
            yield ChatEvent("token", {"text": piece})


# The error event for an exception that ends a reply, with a fixed message and no raw error text
def event_for_error(exc: Exception) -> ChatEvent:
    if isinstance(exc, QuotaExhausted):
        until = exc.blocked_until.isoformat()
        return error_event(
            "quota_exhausted",
            f"We've hit today's free AI limit. Please try again after {until}.",
            blocked_until=until,
        )
    if isinstance(exc, Conflict):
        return error_event(
            "conflict", "The plan is being regenerated or has changed. Please reload and try again."
        )
    if isinstance(exc, NotFound):
        return error_event("not_found", "That trip or conversation no longer exists.")
    if isinstance(exc, InvalidLLMOutput):
        return error_event(
            "invalid_output", "The AI gave an answer I could not use. Please try again."
        )
    return error_event("llm_unavailable", "The AI is busy right now. Please try again in a moment.")
