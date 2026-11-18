"""One chat turn: validate the message, classify it, run the handler, stream the reply."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg_pool import ConnectionPool

from agents.orchestrator_agent import OrchestratorAgent
from chat.discovery_turn import Action, run_discovery_turn
from chat.events import REPLY_ERRORS, ChatEvent, event_for_error, token_events
from chat.handlers import (
    ChatContext,
    answer_about_plan,
    answer_from_research,
    edit_plan,
    give_travel_advice,
    load_context,
)
from core.exceptions import Conflict, NotFound, PlanConflict
from core.settings import Settings
from db.repositories import conversations, messages, trips
from db.repositories.messages import MessageRow
from models.model_router import CallContext, ModelRouter, RouterProvider
from orchestration.routing_schema import AgentSpec, RoutingDecision
from service.tavily.search import WebSearch

# The agents the classifier may route to, with the descriptions it sees
CATALOG: tuple[AgentSpec, ...] = (
    AgentSpec(name="plan_answer", description="Answer a question about the plan of the open trip."),
    AgentSpec(
        name="plan_editor",
        description="Change the plan of the open trip: add, move, replace or remove things, "
        "or change its dates, number of travelers, origin or language.",
    ),
    AgentSpec(
        name="trip_research",
        description="Look up new information the plan does not hold, such as "
        '"cheaper hotels near the beach". The step task is the search query.',
    ),
    AgentSpec(
        name="travel_advice",
        description="General travel advice or tips that are not tied to a plan and are not "
        "about choosing a destination for a new trip.",
    ),
    AgentSpec(
        name="discover_ask",
        description="Only while the visitor is looking for WHERE to go for a new trip. A basic "
        "is still missing (rough dates or month, budget, where the trip starts, who travels): "
        "ask one short follow-up question.",
    ),
    AgentSpec(
        name="discover_suggest",
        description="Only while the visitor is looking for WHERE to go for a new trip. The "
        "visitor wants places to go and the basics are known, or asked to just get ideas. The "
        "step task is a web search query for fitting destinations (kind of trip, month, "
        "budget, origin).",
    ),
    AgentSpec(
        name="discover_answer",
        description="Only while the visitor is still choosing a destination for a new trip: a "
        "general question about places, seasons, costs or visas that needs no destination cards.",
    ),
)
# The discovery agents of the catalog and the discovery action each one runs
DISCOVERY_AGENTS: dict[str, Action] = {
    "discover_ask": "ask",
    "discover_suggest": "suggest",
    "discover_answer": "answer",
}


# What a chat turn needs from the outside; the API builds it once and shares it
@dataclass(frozen=True)
class ChatDeps:
    pool: ConnectionPool
    router: ModelRouter
    search: WebSearch
    settings: Settings
    now: Callable[[], datetime]


# A validated message: the saved user message and what the visitor had open
@dataclass(frozen=True)
class ChatTurn:
    conversation_id: UUID
    user_id: UUID
    message: MessageRow
    trip_id: UUID | None
    plan_revision: int | None


# The assistant reply as it builds up: its intent and the text streamed so far
@dataclass
class _Reply:
    intent: str | None = None
    parts: list[str] = field(default_factory=list)


# Check the message against the conversation and the open trip, then save it; nothing streams yet
def prepare_message(
    conn: Connection[Any],
    conversation_id: UUID,
    content: str,
    trip_id: UUID | None,
    plan_revision: int | None,
    retention_days: int = 30,
) -> ChatTurn:
    conversation = conversations.get_conversation(conn, conversation_id)
    if trip_id is not None:
        trip = trips.get_trip(conn, trip_id)
        if trip.user_id != conversation.user_id:
            raise NotFound(f"trip {trip_id}")
        if plan_revision is not None and plan_revision != trip.plan_revision:
            raise PlanConflict(f"trip {trip_id} is at revision {trip.plan_revision}")
        if trip.plan is None:
            raise Conflict(f"trip {trip_id} has no plan yet")

    message = messages.add_message(conn, conversation_id, "user", content)
    conversations.touch_conversation(conn, conversation_id)
    if trip_id is not None:
        trips.touch(conn, trip_id, retention_days)
    # Commit now: the call log of the stream refers to this message from other connections
    conn.commit()
    return ChatTurn(conversation_id, conversation.user_id, message, trip_id, plan_revision)


# Stream the reply: tokens, a plan or suggestions event, then done. The assistant message is
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
                messages.add_message(conn, turn.conversation_id, "assistant", text, reply.intent)
    yield ChatEvent("done", {})


# Classify the message and run the handler of its intent
def _dispatch(turn: ChatTurn, deps: ChatDeps, reply: _Reply) -> Iterator[ChatEvent]:
    call_ctx = CallContext(
        trip_id=turn.trip_id, conversation_id=turn.conversation_id, message_id=turn.message.id
    )
    with deps.pool.connection() as conn:
        data = load_context(conn, turn)
    decision = _classify(data, turn, deps, call_ctx)

    if decision.status == "needs_clarification":
        reply.intent = "clarification"
        yield from token_events(decision.clarification or "")
        return

    # ponytail: only the first step runs; a multi-step decision is cut to its first agent
    step = decision.steps[0] if decision.status == "routed" else None
    agent = step.agent if step is not None else "fallback"
    if agent == "fallback":
        agent = "plan_answer" if turn.trip_id else "travel_advice"
    if agent == "plan_answer" and data.plan is None:
        agent = "travel_advice"

    if agent in DISCOVERY_AGENTS:
        # The discovery turn saves its own assistant message
        task = step.task if step is not None else None
        yield from run_discovery_turn(turn, deps, DISCOVERY_AGENTS[agent], task)
        return
    reply.intent = agent
    match agent:
        case "plan_editor":
            yield from edit_plan(data, turn, deps, call_ctx)
        case "trip_research":
            query = step.task if step is not None else turn.message.content
            yield from answer_from_research(data, turn, deps, call_ctx, query)
        case "travel_advice":
            yield from give_travel_advice(data, turn, deps, call_ctx)
        case _:
            yield from answer_about_plan(data, turn, deps, call_ctx)


# Ask the classifier where the message goes, with the last messages as history
def _classify(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> RoutingDecision:
    provider = RouterProvider(deps.router, "classify", call_ctx)
    agent = OrchestratorAgent(model_id=provider.model_id, inference_config={}, llm=provider)
    history = [{"role": m.role, "content": m.content} for m in data.history]
    return agent.route([*history, {"role": "user", "content": turn.message.content}], CATALOG)
