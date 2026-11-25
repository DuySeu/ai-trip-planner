"""Request and response bodies of the conversation routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator

from db.repositories.conversations import ConversationRow
from db.repositories.messages import MessageRow
from domain.booking import BookingDates
from domain.discovery import RequestDraft, merge_draft
from domain.trip_request import PlaceText, clean_text

MAX_MESSAGE_CHARS = 4000
MAX_TITLE_CHARS = 80


# NFC, no control characters, trimmed, and at least one character left
def _required_text(max_len: int) -> AfterValidator:
    # Clean the value, then refuse it when nothing is left
    def check(value: str) -> str:
        cleaned = clean_text(value, max_len)
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    return AfterValidator(check)


# Keep only the draft fields the visitor filled in, checked against the draft's own rules
def _clean_draft(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if value is None else merge_draft({}, RequestDraft.model_validate(value))


MessageText = Annotated[str, _required_text(MAX_MESSAGE_CHARS)]
TitleText = Annotated[str, _required_text(MAX_TITLE_CHARS)]


# Body of POST /conversations: who it is for and the form fields entered so far
class CreateConversationBody(BaseModel):
    user_id: UUID
    draft: Annotated[dict[str, Any] | None, AfterValidator(_clean_draft)] = None
    # Checked against the provider's chat models by the route; null means "Auto"
    chat_model: str | None = None


# Body of PATCH /conversations/{id}: a new title, a chat model (null resets to "Auto"), or both
class UpdateConversationBody(BaseModel):
    title: TitleText | None = None
    chat_model: str | None = None

    # At least one field; an explicit null chat_model counts, a null title does not
    @model_validator(mode="after")
    def check_fields(self) -> UpdateConversationBody:
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title must not be null")
        if not self.model_fields_set:
            raise ValueError("send title or chat_model")
        return self


# Body of PATCH /conversations/{id}/messages/{id} that cancels an open trip form
class CancelFormBody(BaseModel):
    status: Literal["canceled"]


# Body of PATCH /conversations/{id}/messages/{id} that answers one step of an open questionnaire:
# a button id in choice, or typed values in answers with choice null; both empty skips the step
class AnswerQuestionBody(BaseModel):
    step: int = Field(ge=1, le=6)
    choice: str | list[str] | None = None
    answers: dict[str, Any] = {}


# Body of POST /chat: the conversation, the text, and the trip open on screen, if any. A card's id
# skips the router: discover_message_id asks for suggestions, booking_message_id searches with the
# dates (and origin) chosen on the card
class SendMessageBody(BaseModel):
    conversation_id: UUID
    content: MessageText
    trip_id: UUID | None = None
    plan_revision: int | None = None
    discover_message_id: UUID | None = None
    booking_message_id: UUID | None = None
    dates: BookingDates | None = None
    origin: PlaceText | None = None
    # The visitor's current city, the starting point when nothing else names one; never saved
    default_origin: PlaceText | None = None

    # One card at a time, and a booking card needs its dates
    @model_validator(mode="after")
    def _one_follow_up(self) -> SendMessageBody:
        if self.discover_message_id is not None and self.booking_message_id is not None:
            raise ValueError("send discover_message_id or booking_message_id, not both")
        if self.booking_message_id is not None and self.dates is None:
            raise ValueError("booking_message_id needs dates")
        return self


# One message of a conversation
class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    intent: str | None
    metadata: dict[str, Any] | None
    created_at: datetime


# One conversation of a list
class ConversationOut(BaseModel):
    id: UUID
    user_id: UUID
    title: str | None
    request_draft: dict[str, Any] | None
    chat_model: str | None
    created_at: datetime
    updated_at: datetime


# A conversation with one page of its messages
class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


# The public view of a conversation row
def conversation_out(row: ConversationRow) -> ConversationOut:
    return ConversationOut(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        request_draft=row.request_draft,
        chat_model=row.chat_model,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# The public view of a message row
def message_out(row: MessageRow) -> MessageOut:
    return MessageOut(
        id=row.id,
        role=row.role,
        content=row.content,
        intent=row.intent,
        metadata=row.metadata,
        created_at=row.created_at,
    )
