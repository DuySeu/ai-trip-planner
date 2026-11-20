"""Request and response bodies of the conversation routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel

from db.repositories.conversations import ConversationRow
from db.repositories.messages import MessageRow
from domain.discovery import RequestDraft, merge_draft
from domain.trip_request import clean_text

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


# Body of PATCH /conversations/{id}
class RenameBody(BaseModel):
    title: TitleText


# Body of PATCH /conversations/{id}/messages/{id}: the only change allowed is canceling a trip form
class CloseTripFormBody(BaseModel):
    intent: Literal["canceled_trip"]


# Body of POST /chat: the conversation, the text, and the trip open on screen, if any
class SendMessageBody(BaseModel):
    conversation_id: UUID
    content: MessageText
    trip_id: UUID | None = None
    plan_revision: int | None = None


# One message of a conversation
class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    intent: str | None
    suggestions: list[Any] | None
    created_at: datetime


# One conversation of a list
class ConversationOut(BaseModel):
    id: UUID
    user_id: UUID
    title: str | None
    request_draft: dict[str, Any] | None
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
        suggestions=row.suggestions,
        created_at=row.created_at,
    )
