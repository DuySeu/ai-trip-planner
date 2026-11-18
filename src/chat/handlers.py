"""What the chat does for each intent: answer, edit the plan, research, give advice."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from psycopg import Connection

from chat.events import ChatEvent, token_events
from core.exceptions import Conflict, EditRejected, InvalidLLMOutput, ResearchFailed
from core.prompts import (
    plan_answer_prompt,
    travel_advice_prompt,
    trip_research_answer_prompt,
)
from db.repositories import jobs, messages, research, trips
from db.repositories.messages import MessageRow
from db.repositories.research import SourceInput, SourceRow
from db.repositories.trips import TripRow
from domain.budget import over_budget_vnd, total_cost_vnd
from domain.plan import Plan, PlanWarning
from domain.plan_edit import apply_edit
from domain.plan_rules import check_plan
from domain.trip_request import (
    TripRequest,
    budget_total_vnd,
    today_in_vietnam,
    validate_request,
)
from models.model_router import CallContext
from planning.plan_editor import compact_plan, propose_edit
from service.tavily.search import SearchHit

if TYPE_CHECKING:
    # Imported for annotations only: chat_service imports this module
    from collections.abc import Iterator

    from chat.chat_service import ChatDeps, ChatTurn

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 10
MAX_TRIPS_IN_CONTEXT = 20
MAX_SOURCES_PER_KIND = 3
VIETNAMESE_LETTER = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE
)
# Replies written by code, as (English, Vietnamese)
OPEN_TRIP = (
    "Open the trip you want to change first, then ask me again.",
    "Hãy mở chuyến đi bạn muốn thay đổi rồi nhắn lại cho mình nhé.",
)
CANNOT_APPLY = (
    "I could not turn that into a valid change to the plan. Please say which item to change and how.",
    "Mình chưa thể biến yêu cầu đó thành một thay đổi hợp lệ. Hãy nói rõ mục nào cần đổi và đổi thế nào nhé.",
)
CANNOT_REQUEST = (
    "I cannot make that change: {errors}",
    "Mình không thể thay đổi như vậy: {errors}",
)
REPLAN_STARTED = (
    "Re-planning has started. The current plan stays here until the new one is ready.",
    "Đã bắt đầu lập lại kế hoạch. Kế hoạch hiện tại vẫn ở đây cho tới khi bản mới xong.",
)
CHANGED = ("Changed:", "Đã đổi:")


# One of the (English, Vietnamese) texts, by whether the visitor's message looks Vietnamese.
# ponytail: a diacritics check; Vietnamese typed without accents gets English, add a detector if it matters
def localized(message: str, texts: tuple[str, str]) -> str:
    return texts[1] if VIETNAMESE_LETTER.search(message) else texts[0]


# Everything a handler may put in front of the model for one turn
@dataclass(frozen=True)
class ChatContext:
    trips: str
    trip: TripRow | None
    request: TripRequest | None
    plan: Plan | None
    sources: tuple[SourceRow, ...]
    history: tuple[MessageRow, ...]


# Web text as data: angle brackets are replaced so it cannot close or open a tag
def data_text(text: str | None) -> str:
    return " ".join((text or "").replace("<", "(").replace(">", ")").split())


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


# The sources as <source id kind title url>snippet</source> lines
def sources_text(rows: Sequence[SourceRow]) -> str:
    return "\n".join(
        f'<source id="{s.id}" kind="{s.kind}" title="{data_text(s.title)}" '
        f'url="{data_text(s.url)}">{data_text(s.snippet)}</source>'
        for s in rows
    )


# The conversation as "role: text" lines inside <conversation>, or "" when there is none
def conversation_text(history: tuple[MessageRow, ...]) -> str:
    turns = "\n".join(f"{m.role}: {data_text(m.content)}" for m in history)
    return f"<conversation>\n{turns}\n</conversation>" if turns else ""


# The user message for the model: the tagged context, then the visitor's request
def build_prompt(
    data: ChatContext,
    message: str,
    trip_details: bool = True,
    search_results: str | None = None,
) -> str:
    parts = [f"<trips>\n{data.trips}\n</trips>" if data.trips else ""]
    if trip_details and data.trip is not None and data.request is not None:
        r = data.request
        parts.append(
            f"<trip>\ndestination: {r.destination.name} ({r.destination.country_code})\n"
            f"origin: {r.origin}\ndates: {r.start_date.isoformat()} to {r.end_date.isoformat()}\n"
            f"travelers: {r.travelers}\nstyles: {', '.join(r.travel_styles)}\n"
            f"budget: {budget_total_vnd(r):,.0f} VND for the whole group\n"
            f"status: {data.trip.status}\n</trip>"
        )
        if data.plan is not None:
            parts.append(f"<plan>\n{compact_plan(data.plan)}\n</plan>")
        if data.sources:
            # A few sources per kind keep the prompt short
            seen: Counter[str] = Counter()
            few = []
            for source in data.sources:
                seen[source.kind] += 1
                if seen[source.kind] <= MAX_SOURCES_PER_KIND:
                    few.append(source)
            parts.append(f"<sources>\n{sources_text(few)}\n</sources>")
    if search_results is not None:
        parts.append(f"<search_results>\n{search_results or 'none'}\n</search_results>")
    parts += [conversation_text(data.history), f"<request>\n{message}\n</request>"]
    return "\n\n".join(p for p in parts if p)


# Stream the model's answer as token events
def stream_answer(
    deps: ChatDeps, system: str, content: str, call_ctx: CallContext
) -> Iterator[ChatEvent]:
    messages_in = [{"role": "user", "content": content}]
    for text in deps.router.stream("answer", messages_in, system, call_ctx):
        yield ChatEvent("token", {"text": text})


# A question about the plan of the open trip
def answer_about_plan(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> Iterator[ChatEvent]:
    content = build_prompt(data, turn.message.content)
    yield from stream_answer(deps, plan_answer_prompt, content, call_ctx)


# General advice that is not tied to a plan
def give_travel_advice(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> Iterator[ChatEvent]:
    content = build_prompt(data, turn.message.content, trip_details=False)
    yield from stream_answer(deps, travel_advice_prompt, content, call_ctx)


# Search the web once (twice when the first search finds nothing), keep the hits, answer from them
def answer_from_research(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext, query: str
) -> Iterator[ChatEvent]:
    hits: list[SearchHit] = []
    for text in (query, f"{query} travel guide"):
        try:
            hits = deps.search(text, "chat")
        except ResearchFailed as exc:
            logger.warning("chat search failed: %s", exc)
            break
        if hits:
            break

    # Keep the hits as sources of the trip, or of the conversation when no trip is open
    saved: list[SourceRow] = []
    if hits:
        with deps.pool.connection() as conn:
            saved = research.save_sources(
                conn,
                trip_id=turn.trip_id,
                conversation_id=None if turn.trip_id else turn.conversation_id,
                kind="chat",
                items=[SourceInput(h.title, h.url, h.content) for h in hits],
            )

    content = build_prompt(data, turn.message.content, search_results=sources_text(saved))
    yield from stream_answer(deps, trip_research_answer_prompt, content, call_ctx)


# Apply the visitor's change: save the new plan (or queue a re-plan) before any text is streamed
def edit_plan(
    data: ChatContext, turn: ChatTurn, deps: ChatDeps, call_ctx: CallContext
) -> Iterator[ChatEvent]:
    message = turn.message.content
    trip, request, plan = data.trip, data.request, data.plan
    if turn.plan_revision is None or trip is None or request is None or plan is None:
        yield from token_events(localized(message, OPEN_TRIP))
        return

    # Edits wait while a re-plan runs
    with deps.pool.connection() as conn:
        busy = jobs.active_job(conn, trip.id) is not None
    if busy:
        raise Conflict("plan is being regenerated")

    # Ask for the edit and apply it to a copy; a bad one is answered in words, never saved
    try:
        proposal = propose_edit(deps.router, request, plan, data.history, message, call_ctx)
        result = apply_edit(plan, proposal.value, request)
    except (InvalidLLMOutput, EditRejected) as exc:
        logger.info("edit refused: %s", exc)
        yield from token_events(localized(message, CANNOT_APPLY))
        return
    explanation = proposal.value.explanation

    # A change of the request queues a re-plan; the trip keeps its request until the new plan lands
    if result.request_changes is not None:
        changes = result.request_changes.model_dump(exclude_none=True)
        new_request = TripRequest.model_validate({**request.model_dump(), **changes})
        today = today_in_vietnam(deps.now())
        if "start_date" not in changes:
            today = min(today, request.start_date)
        errors = validate_request(new_request, today)
        if errors:
            text = localized(message, CANNOT_REQUEST).format(errors="; ".join(errors))
            yield from token_events(text)
            return
        with deps.pool.connection() as conn:
            jobs.enqueue(conn, trip.id, request=new_request.model_dump(mode="json"))
        yield from token_events(f"{explanation}\n\n{localized(message, REPLAN_STARTED)}")
        return

    # Rule-check the edited plan, refresh the budget warning, then save it with the client's revision
    checked = check_plan(result.plan, request, frozenset(s.id for s in data.sources))
    if checked.errors:
        logger.info("edited plan breaks rules: %s", checked.errors)
        yield from token_events(localized(message, CANNOT_APPLY))
        return
    over = over_budget_vnd(checked.plan, request)
    warnings = tuple(w for w in checked.plan.warnings if w.code != "over_budget")
    if over > 0:
        warnings += (
            PlanWarning(
                code="over_budget",
                message=f"The plan is {over:,.0f} VND over the budget of "
                f"{budget_total_vnd(request):,.0f} VND.",
            ),
        )
    new_plan = checked.plan.model_copy(update={"warnings": warnings})
    with deps.pool.connection() as conn:
        saved = trips.save_plan(
            conn,
            trip.id,
            turn.plan_revision,
            new_plan.model_dump(mode="json"),
            total_cost_vnd(new_plan, request.travelers),
            over > 0,
            trip.model_id,
        )
    yield ChatEvent("plan", {"plan_revision": saved.plan_revision})
    changed = "\n".join(f"- {line}" for line in result.changed)
    yield from token_events(f"{explanation}\n\n{localized(message, CHANGED)}\n{changed}")
