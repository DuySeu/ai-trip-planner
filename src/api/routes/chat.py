"""Conversation routes: start, list, read, rename, delete, and the streamed chat reply."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from api.deps import Conn, Deps, limit_chat, require_quota
from api.envelope import ApiResponse, PageMeta
from api.schemas.chat import (
    AnswerQuestionBody,
    CancelFormBody,
    ConversationDetail,
    ConversationOut,
    CreateConversationBody,
    MessageOut,
    RenameBody,
    SendMessageBody,
    conversation_out,
    message_out,
)
from chat.chat_service import ChatDeps, ChatTurn, FollowUp, prepare_message, stream_reply
from chat.events import to_sse
from chat.guard_turn import GUARDRAIL_CONFIG
from chat.questionnaire_service import answer_questionnaire
from core.exceptions import Conflict, LimitExceeded, NotFound
from db.repositories import conversations, messages, users
from domain.trip_request import today_in_vietnam
from research.cache import DbCache
from research.places import search_places

router = APIRouter()

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_MESSAGES = 50
MAX_MESSAGES = 200
MAX_TITLE_CHARS = 80
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


# What a chat turn needs, built from the shared services; the search goes through the cache
def get_chat_deps(deps: Deps) -> ChatDeps:
    cache = DbCache(deps.pool)
    return ChatDeps(
        deps.pool,
        deps.router,
        deps.search,
        deps.settings,
        deps.now,
        lambda q, language: search_places(deps.http, cache, q, language),
        GUARDRAIL_CONFIG,
    )


ChatDepsDep = Annotated[ChatDeps, Depends(get_chat_deps)]


# The reply as server-sent events. When the client leaves, this generator is closed and drops
# the reply generator, whose own `finally` saves the text sent so far (CPython closes on drop).
def sse_stream(turn: ChatTurn, chat_deps: ChatDeps) -> Iterator[str]:
    for event in stream_reply(turn, chat_deps):
        yield to_sse(event)


# POST /conversations - Start a conversation, optionally with the form fields entered so far
@router.post("/conversations", status_code=201)
def create_conversation(body: CreateConversationBody, conn: Conn) -> ApiResponse[ConversationOut]:
    users.get_user(conn, body.user_id)
    row = conversations.create_conversation(conn, body.user_id, body.draft)
    conn.commit()
    return ApiResponse(success=True, data=conversation_out(row))


# GET /users/{user_id}/conversations - A user's conversations, most recently active first, paged
@router.get("/users/{user_id}/conversations")
def list_user_conversations(
    user_id: UUID,
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[list[ConversationOut]]:
    users.get_user(conn, user_id)
    rows = conversations.list_conversations(conn, user_id, limit, offset)
    return ApiResponse(
        success=True,
        data=[conversation_out(row) for row in rows],
        meta=PageMeta(
            total=conversations.count_conversations(conn, user_id), limit=limit, offset=offset
        ),
    )


# GET /conversations/{conversation_id} - A conversation with its draft and a page of messages
@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=MAX_MESSAGES)] = DEFAULT_MESSAGES,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ConversationDetail]:
    row = conversations.get_conversation(conn, conversation_id)
    page = messages.list_messages(conn, conversation_id, limit, offset)
    detail = ConversationDetail(
        **conversation_out(row).model_dump(), messages=[message_out(m) for m in page]
    )
    return ApiResponse(
        success=True,
        data=detail,
        meta=PageMeta(
            total=messages.count_messages(conn, conversation_id), limit=limit, offset=offset
        ),
    )


# PATCH /conversations/{conversation_id} - Rename; updated_at stays so the list order holds
@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: UUID, body: RenameBody, conn: Conn
) -> ApiResponse[ConversationOut]:
    row = conversations.rename_conversation(conn, conversation_id, body.title)
    conn.commit()
    return ApiResponse(success=True, data=conversation_out(row))


# PATCH /conversations/{conversation_id}/messages/{message_id} - Cancel an open trip form, or
# answer one step of an open questionnaire card
@router.patch("/conversations/{conversation_id}/messages/{message_id}")
def update_message(
    conversation_id: UUID,
    message_id: UUID,
    body: CancelFormBody | AnswerQuestionBody,
    conn: Conn,
    deps: Deps,
) -> ApiResponse[MessageOut]:
    if isinstance(body, AnswerQuestionBody):
        today = today_in_vietnam(deps.now())
        saved = answer_questionnaire(
            conn, conversation_id, message_id, body.step, body.choice, body.answers, today
        )
        conn.commit()
        return ApiResponse(success=True, data=message_out(saved))

    form = messages.get_message(conn, message_id)
    if form.conversation_id != conversation_id:
        raise NotFound(f"message {message_id}")
    if form.intent != "create_trip":
        raise Conflict(f"message {message_id} is not a trip form")
    canceled = {**(form.metadata or {}), "status": "canceled"}
    closed = messages.update_open_metadata(conn, message_id, {"status": "open"}, canceled)
    if closed is None:
        raise Conflict("This form was already used")
    conn.commit()
    return ApiResponse(success=True, data=message_out(closed))


# DELETE /conversations/{conversation_id} - Delete it and its messages
@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, conn: Conn) -> Response:
    conversations.delete_conversation(conn, conversation_id)
    conn.commit()
    return Response(status_code=204)


# POST /chat - Send a message to the conversation named in the body; the reply is an SSE stream.
# Every check and the save run in one short unit of work, so no pooled connection is held
# while the reply streams (the stream opens its own).
@router.post("/chat", dependencies=[Depends(limit_chat)])
def send_message(body: SendMessageBody, deps: Deps, chat_deps: ChatDepsDep) -> StreamingResponse:
    conversation_id = body.conversation_id
    with deps.pool.connection() as conn:
        owner = conversations.get_conversation(conn, conversation_id).user_id
        if messages.count_user_messages_today(conn, owner) >= deps.settings.user_chat_per_day:
            raise LimitExceeded("Daily message limit reached for this name, try again tomorrow")
        require_quota("chat")(deps, conn)
        follow_up = None
        if body.discover_message_id is not None:
            follow_up = FollowUp(body.discover_message_id, "discover")
        elif body.booking_message_id is not None:
            follow_up = FollowUp(body.booking_message_id, "booking", body.dates, body.origin)
        turn = prepare_message(
            conn,
            conversation_id,
            body.content,
            body.trip_id,
            body.plan_revision,
            follow_up,
            today_in_vietnam(deps.now()),
        )
        conversations.set_title_if_missing(conn, conversation_id, body.content[:MAX_TITLE_CHARS])
    return StreamingResponse(
        sse_stream(turn, chat_deps), media_type="text/event-stream", headers=SSE_HEADERS
    )
