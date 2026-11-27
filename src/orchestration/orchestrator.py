"""One chat turn: guard the message, plan its task, run the handler, stream the reply."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg_pool import ConnectionPool

from core.settings import Settings
from domain.booking import BookingKind
from domain.trip_request import Language
from guardrail import Action
from models.model_router import CallContext, ModelRouter
from orchestration.booking_turn import run_booking_follow_up, run_booking_turn
from orchestration.create_trip_turn import run_create_trip_turn
from orchestration.discovery_turn import run_discover_turn, run_suggest_turn
from orchestration.events import REPLY_ERRORS, ChatEvent, event_for_error, token_events
from orchestration.guard_turn import OFF_TOPIC, check_message
from orchestration.handlers import (
    answer_about_plan,
    answer_from_research,
    edit_plan,
    give_travel_advice,
    localized,
)
from orchestration.state_manager import (
    ChatTurn,
    Reply,
    load_context,
    reopen_on_failure,
    save_reply,
)
from orchestration.task_planner import AGENT_INTENT, classify, plan_task
from research.places import Place
from service.tavily.search import WebSearch

logger = logging.getLogger(__name__)


# What a chat turn needs from the outside; the API builds it once and shares it
@dataclass(frozen=True)
class ChatDeps:
    pool: ConnectionPool
    router: ModelRouter
    search: WebSearch
    settings: Settings
    now: Callable[[], datetime]
    places: Callable[[str, Language], list[Place]]
    # The guardrail config a typed message is checked against before the router; None skips it
    guardrail_config: Mapping[str, Any] | None = None


# Stream the reply: tokens, a plan or metadata event, then done. The assistant message is
# saved with the text sent so far when the stream ends, fails or is closed by the client.
def stream_reply(turn: ChatTurn, deps: ChatDeps) -> Iterator[ChatEvent]:
    reply = Reply()
    try:
        for event in _dispatch(turn, deps, reply):
            if event.type == "token":
                reply.parts.append(event.data["text"])
            yield event
    except REPLY_ERRORS as exc:
        yield event_for_error(exc)
    finally:
        save_reply(reply, turn, deps)
    yield ChatEvent("done", {})


# Classify the message and run the handler of its intent
def _dispatch(turn: ChatTurn, deps: ChatDeps, reply: Reply) -> Iterator[ChatEvent]:
    call_ctx = CallContext(
        trip_id=turn.trip_id,
        conversation_id=turn.conversation_id,
        message_id=turn.message.id,
        chat_model=turn.chat_model,
    )
    with deps.pool.connection() as conn:
        data = load_context(conn, turn)
    if turn.follow_up is not None:
        # The card's id says what to run; these turns save their own assistant message
        if turn.follow_up.kind == "discover":
            follow = run_suggest_turn(turn, deps, call_ctx)
        else:
            follow = run_booking_follow_up(data, turn, deps, call_ctx)
        yield from reopen_on_failure(follow, turn.follow_up, deps)
        return

    # A typed message that is not about travel (or is harmful or an injection) gets a fixed reply
    if deps.guardrail_config is not None:
        verdict = check_message(
            deps.guardrail_config, deps.router, call_ctx, turn.message.content, data.history
        )
        if verdict.action is Action.BLOCK:
            # The pipeline stops at the first block, so the last result is the blocking guard's
            category = verdict.results[-1].category
            logger.info("chat flow: blocked by guard %s (%s)", verdict.blocked_by, category)
            reply.intent = "advice"
            reply.metadata = {"blocked": True, "guard": verdict.blocked_by, "category": category}
            yield from token_events(localized(turn.message.content, OFF_TOPIC))
            return

    decision = classify(data, turn, deps, call_ctx)

    if decision.status == "needs_clarification":
        reply.intent, reply.metadata = "advice", {"clarify": True}
        yield from token_events(decision.clarification or "")
        return

    task = plan_task(decision, turn.message.content)
    agent = task.agent
    logger.info(
        "chat flow: %s (classifier picked %s, %s): %s",
        agent,
        task.picked,
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
        yield from run_booking_turn(data, turn, deps, call_ctx, kind, task.text)
        return

    reply.intent = AGENT_INTENT[agent]
    match agent:
        case "edit_plan":
            yield from edit_plan(data, turn, deps, call_ctx)
        case "web_lookup":
            reply.metadata = {"searched": True}
            yield from answer_from_research(data, turn, deps, call_ctx, task.text)
        case _ if data.plan is not None:
            yield from answer_about_plan(data, turn, deps, call_ctx)
        case _:
            yield from give_travel_advice(data, turn, deps, call_ctx)
