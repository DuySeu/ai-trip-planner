from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from psycopg_pool import ConnectionPool

from chat.chat_service import ChatDeps, prepare_message, stream_reply
from chat.events import ChatEvent, to_sse
from core.constants import ModelId
from core.exceptions import Conflict, NotFound, PlanConflict
from core.settings import load_settings
from db.call_sink import DbCallSink
from db.repositories.conversations import create_conversation
from db.repositories.jobs import active_job, enqueue
from db.repositories.messages import recent_messages
from db.repositories.research import sources_for_trip
from db.repositories.trips import TripRow, create_trip, get_trip, save_plan
from db.repositories.users import UserRow, claim_user
from models.model_router import ModelRouter
from service.tavily.search import SearchHit
from tests.fakes import FakeProvider, FakeSearch, FakeSink
from tests.fixtures.builders import DALAT_FIELDS, dalat_plan

MODEL = ModelId.GEMMA_4_31B_IT
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
ENV = {
    "DB_USER": "u",
    "DB_PASSWORD": "p",
    "DB_NAME": "n",
    "OPENROUTER_API_KEY": "k",
    "TAVILY_API_KEY": "k",
    "PLANNER_MODELS": MODEL,
    "CHAT_MODELS": MODEL,
    "CLASSIFIER_MODELS": MODEL,
    "DAILY_LLM_CEILING_NEW_TRIPS": "10",
    "DAILY_LLM_CEILING_CHAT": "20",
    "DAILY_TAVILY_CEILING": "10",
}
PURPOSES = ("classify", "edit", "repair", "answer", "discover", "suggest")
ANSWER = "The stay is near the lake, so you can walk to the market."
HITS = [SearchHit("Train guide", "https://example.com/t", "The night bus costs 350000 VND.")]


# The classifier's JSON for one routed step
def route(agent: str, task: str = "do it") -> str:
    step = {"id": "s1", "agent": agent, "task": task}
    return json.dumps(
        {
            "status": "routed",
            "architecture": "router",
            "steps": [step],
            "aggregation": None,
            "clarification": None,
            "reasoning": "fits",
        }
    )


# An edit answer: operations plus the explanation
def edit_answer(*ops: dict[str, Any]) -> str:
    return json.dumps({"ops": list(ops), "explanation": "Renamed the walk."})


RENAME = edit_answer(
    {"op": "update_item", "item_id": "it_3", "changes": {"title": "Cafe by the lake"}}
)
CHANGE_TRAVELERS = edit_answer({"op": "update_request", "changes": {"travelers": 3}})


# Everything one test needs: a provider that scripts the model, the deps and the stand-ins
class Rig:
    def __init__(
        self,
        pool: ConnectionPool,
        script: Sequence[str | Exception],
        search: FakeSearch | None = None,
        provider: FakeProvider | None = None,
        sink: DbCallSink | FakeSink | None = None,
    ) -> None:
        self.provider = provider or FakeProvider(script)
        self.sink = sink or FakeSink()
        self.search = search or FakeSearch(default=HITS)
        self.pool = pool
        router = ModelRouter(
            provider_for=lambda model_id: self.provider,
            models={purpose: [MODEL] for purpose in PURPOSES},  # type: ignore[misc]
            sink=self.sink,
            daily_cap_pattern="free-models-per-day",
            reset_hour_utc=0,
            now=lambda: NOW,
        )
        self.deps = ChatDeps(
            pool, router, self.search, load_settings(ENV), lambda: NOW, lambda q, language: []
        )
        self.router = router

    # Save the visitor's message and stream the reply to the end
    def say(
        self,
        conversation_id: Any,
        content: str,
        trip: TripRow | None = None,
        revision: int | None = None,
    ) -> list[ChatEvent]:
        with self.pool.connection() as conn:
            turn = prepare_message(
                conn, conversation_id, content, trip.id if trip else None, revision
            )
        return list(stream_reply(turn, self.deps))


@pytest.fixture
def user(db_conn) -> UserRow:
    return claim_user(db_conn, "Duy")


@pytest.fixture
def conversation(db_conn, user):
    return create_conversation(db_conn, user.id, None)


# A ready Da Lat trip of the user at plan revision 1
@pytest.fixture
def ready_trip(db_conn, user) -> TripRow:
    trip = create_trip(db_conn, user.id, DALAT_FIELDS, None, retention_days=30)
    return save_plan(
        db_conn, trip.id, 0, dalat_plan().model_dump(mode="json"), Decimal("1000000"), False, "m"
    )


# The text of the token events, joined
def spoken(events: Sequence[ChatEvent]) -> str:
    return "".join(e.data["text"] for e in events if e.type == "token")


def test_question_streams_answer_and_saves_both_messages(
    db_pool, db_conn, conversation, ready_trip
):
    rig = Rig(db_pool, [route("plan_answer"), ANSWER])
    events = rig.say(conversation.id, "Where is the stay?", ready_trip, ready_trip.plan_revision)

    assert spoken(events) == ANSWER
    assert events[-1] == ChatEvent("done", {})
    saved = recent_messages(db_conn, conversation.id, 5)
    assert [(m.role, m.content, m.intent) for m in saved] == [
        ("user", "Where is the stay?", None),
        ("assistant", ANSWER, "plan_answer"),
    ]
    # The answer call saw the plan with its ids and the question
    content = rig.provider.calls[1][0][0]["content"]
    assert "it_3" in content and "Where is the stay?" in content


def test_question_without_open_trip_gets_travel_advice(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [route("plan_answer"), "Bring a light jacket."])
    events = rig.say(conversation.id, "What should I pack for Sapa?")
    assert spoken(events) == "Bring a light jacket."
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "travel_advice"


def test_routing_logs_the_chosen_flow_and_the_reason(db_pool, conversation, caplog):
    rig = Rig(db_pool, [route("plan_answer"), "Bring a light jacket."])
    with caplog.at_level(logging.INFO, logger="chat.chat_service"):
        rig.say(conversation.id, "What should I pack for Sapa?")
    assert "chat flow: travel_advice (classifier picked plan_answer, routed): fits" in caplog.text


def test_trip_of_another_user_raises_not_found_before_streaming(
    db_pool, db_conn, conversation, ready_trip
):
    other = create_conversation(db_conn, claim_user(db_conn, "Mai").id, None)
    with db_pool.connection() as conn, pytest.raises(NotFound):
        prepare_message(conn, other.id, "hi", ready_trip.id, ready_trip.plan_revision)
    assert recent_messages(db_conn, other.id, 5) == []


def test_stale_plan_revision_raises_before_streaming(db_pool, db_conn, conversation, ready_trip):
    with db_pool.connection() as conn, pytest.raises(PlanConflict):
        prepare_message(conn, conversation.id, "hi", ready_trip.id, ready_trip.plan_revision - 1)
    assert recent_messages(db_conn, conversation.id, 5) == []


def test_trip_without_plan_raises_conflict_before_streaming(db_pool, db_conn, user, conversation):
    queued = create_trip(db_conn, user.id, DALAT_FIELDS, None, retention_days=30)
    with db_pool.connection() as conn, pytest.raises(Conflict):
        prepare_message(conn, conversation.id, "hi", queued.id, None)


def test_edit_without_open_trip_asks_to_open_it(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [route("plan_editor")])
    events = rig.say(conversation.id, "Move lunch to 13:00")
    assert "Open the trip" in spoken(events)
    assert len(rig.provider.calls) == 1
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "plan_editor"


def test_edit_without_open_trip_answers_a_vietnamese_message_in_vietnamese(db_pool, conversation):
    rig = Rig(db_pool, [route("plan_editor")])
    events = rig.say(conversation.id, "Đổi bữa trưa sang 13:00")
    assert "Hãy mở chuyến đi" in spoken(events)


def test_classifier_chooses_discover_ask_without_a_second_decision_call(
    db_pool, db_conn, conversation
):
    turn = json.dumps(
        {"reply": "When do you want to travel?", "request_draft": {"origin": "Hanoi"}}
    )
    rig = Rig(db_pool, [route("discover_ask"), turn])
    events = rig.say(conversation.id, "I do not know where to go")
    assert spoken(events) == "When do you want to travel?"
    assert events[-1].type == "done"
    assert len(rig.provider.calls) == 2
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "ask"


def test_discover_suggest_searches_the_router_task_and_makes_two_calls_in_all(
    db_pool, db_conn, conversation
):
    task = "warm beach trips in December from Hanoi"
    card = {
        "name": "Krabi",
        "country_code": "TH",
        "why": "Dry in December.",
        "length_days": 4,
        "est_cost_per_person_vnd": "9000000",
        "source_ids": [1],
    }
    answer = json.dumps({"reply": "I assume two travelers.", "request_draft": {}, "cards": [card]})
    rig = Rig(db_pool, [route("discover_suggest", task), answer])
    events = rig.say(conversation.id, "Warm beach in December, no idea where")
    assert rig.search.calls[0] == task and len(rig.provider.calls) == 2
    assert [e.type for e in events][-2:] == ["suggestions", "done"]
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "suggest"


def test_discover_answer_makes_two_calls_in_all_and_no_search(db_pool, db_conn, conversation):
    turn = json.dumps({"reply": "December is dry in the south.", "request_draft": {}})
    rig = Rig(db_pool, [route("discover_answer"), turn])
    rig.say(conversation.id, "Is December a good month for Thailand?")
    assert rig.search.calls == [] and len(rig.provider.calls) == 2
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "answer"


def test_llm_calls_carry_the_user_message_id(db_pool, db_conn, conversation, ready_trip):
    rig = Rig(db_pool, [route("plan_answer"), ANSWER], sink=DbCallSink(db_pool))
    rig.say(conversation.id, "Where is the stay?", ready_trip, ready_trip.plan_revision)
    user_message = recent_messages(db_conn, conversation.id, 2)[0]
    rows = db_conn.execute(
        "SELECT purpose, trip_id, conversation_id, message_id FROM llm_calls ORDER BY id"
    ).fetchall()
    assert rows == [
        ("classify", ready_trip.id, conversation.id, user_message.id),
        ("answer", ready_trip.id, conversation.id, user_message.id),
    ]


def test_edit_overwrites_plan_before_any_token(db_pool, db_conn, conversation, ready_trip):
    rig = Rig(db_pool, [route("plan_editor"), RENAME])
    events = rig.say(conversation.id, "Rename the walk", ready_trip, ready_trip.plan_revision)

    assert events[0] == ChatEvent("plan", {"plan_revision": ready_trip.plan_revision + 1})
    assert events[1].type == "token"
    text = spoken(events)
    assert "Renamed the walk." in text and "Updated it_3 Cafe by the lake" in text
    saved = get_trip(db_conn, ready_trip.id)
    assert saved.plan_revision == ready_trip.plan_revision + 1
    assert saved.plan is not None
    titles = [i["title"] for d in saved.plan["days"] for i in d["items"]]
    assert "Cafe by the lake" in titles and saved.model_id == "m"


def test_edit_that_cannot_be_repaired_is_a_polite_reply_and_saves_no_plan(
    db_pool, db_conn, conversation, ready_trip
):
    bad = edit_answer({"op": "remove_item", "item_id": "it_999"})
    rig = Rig(db_pool, [route("plan_editor"), bad, bad])
    events = rig.say(conversation.id, "Drop it_999", ready_trip, ready_trip.plan_revision)
    assert [e.type for e in events] == ["token"] * (len(events) - 1) + ["done"]
    assert "could not turn that" in spoken(events)
    assert get_trip(db_conn, ready_trip.id).plan_revision == ready_trip.plan_revision


def test_edit_while_job_active_yields_conflict_error_event(
    db_pool, db_conn, conversation, ready_trip
):
    enqueue(db_conn, ready_trip.id)
    rig = Rig(db_pool, [route("plan_editor")])
    events = rig.say(conversation.id, "Rename the walk", ready_trip, ready_trip.plan_revision)
    assert [e.type for e in events] == ["error", "done"]
    assert events[0].data["code"] == "conflict"
    assert len(rig.provider.calls) == 1
    assert get_trip(db_conn, ready_trip.id).plan_revision == ready_trip.plan_revision
    assert [m.role for m in recent_messages(db_conn, conversation.id, 5)] == ["user"]


def test_update_request_queues_replan_job(db_pool, db_conn, conversation, ready_trip):
    rig = Rig(db_pool, [route("plan_editor"), CHANGE_TRAVELERS])
    events = rig.say(conversation.id, "We are 3 people", ready_trip, ready_trip.plan_revision)

    assert "plan" not in [e.type for e in events]
    assert "Re-planning has started" in spoken(events)
    job = active_job(db_conn, ready_trip.id)
    assert job is not None and job.request is not None and job.request["travelers"] == 3
    trip = get_trip(db_conn, ready_trip.id)
    assert (trip.travelers, trip.plan_revision) == (4, ready_trip.plan_revision)


def test_update_request_with_invalid_dates_queues_nothing(
    db_pool, db_conn, conversation, ready_trip
):
    early = edit_answer(
        {"op": "update_request", "changes": {"start_date": "2026-01-01", "end_date": "2026-01-03"}}
    )
    rig = Rig(db_pool, [route("plan_editor"), early])
    events = rig.say(conversation.id, "Go in January", ready_trip, ready_trip.plan_revision)
    assert "cannot make that change" in spoken(events)
    assert active_job(db_conn, ready_trip.id) is None


def test_research_searches_once_with_router_task_text(db_pool, db_conn, conversation, ready_trip):
    task = "train or bus Da Lat to Nha Trang, 4 people, 21 Dec"
    rig = Rig(db_pool, [route("trip_research", task), "The night bus costs about 350000 VND."])
    events = rig.say(conversation.id, "Bus or train to Nha Trang?", ready_trip, 1)

    assert rig.search.calls == [task]
    assert rig.search.tasks == ["chat"]
    assert "350000" in spoken(events)
    saved = [s for s in sources_for_trip(db_conn, ready_trip.id) if s.kind == "chat"]
    assert [(s.title, s.url) for s in saved] == [("Train guide", "https://example.com/t")]
    assert "Train guide" in rig.provider.calls[1][0][0]["content"]
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "trip_research"


def test_research_searches_again_only_when_first_search_is_empty(db_pool, conversation):
    search = FakeSearch({"cheap stay": []}, default=HITS)
    rig = Rig(db_pool, [route("trip_research", "cheap stay"), "Try the old town."], search)
    rig.say(conversation.id, "Cheap stay?")
    assert search.calls == ["cheap stay", "cheap stay travel guide"]


def test_research_without_trip_keeps_hits_on_the_conversation(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [route("trip_research", "visa for Japan"), "Check the embassy."])
    rig.say(conversation.id, "Visa for Japan?")
    row = db_conn.execute("SELECT kind, trip_id, conversation_id FROM research_results").fetchall()
    assert row == [("chat", None, conversation.id)]


HOTEL_HITS = [
    SearchHit(
        "Mercure Hai Phong", "https://www.booking.com/hotel/vn/mercure.html", "From 1,450,000 VND"
    ),
    SearchHit("The Light Hotel", "https://www.agoda.com/the-light", "4-star hotel in Ngo Quyen"),
]
HOTEL_QUESTION = "khách sạn ở Hải Phòng 4 sao khoảng bao nhiêu tiền/đêm"


# The model's answer for a hotel question
def hotel_answer(reply: str, *cards: dict[str, Any]) -> str:
    return json.dumps({"reply": reply, "cards": list(cards)})


def test_hotel_question_searches_booking_sites_and_streams_cards(db_pool, db_conn, conversation):
    task = "khách sạn 4 sao Hải Phòng giá mỗi đêm"
    search = FakeSearch(default=HOTEL_HITS)
    answer = hotel_answer(
        "Giá tham khảo từ các trang đặt phòng.",
        {"name": "The Light", "stars": 4, "source_id": 2},
        {
            "name": "Mercure",
            "area": "Ngô Quyền",
            "stars": 4,
            "price_per_night": "1450000",
            "source_id": 1,
        },
        {"name": "Made up", "source_id": 99},
    )
    rig = Rig(db_pool, [route("hotel_options", task), answer], search)
    events = rig.say(conversation.id, HOTEL_QUESTION)

    assert (search.calls, search.tasks) == ([task], ["accommodation"])
    assert spoken(events) == "Giá tham khảo từ các trang đặt phòng."
    assert [e.type for e in events][-2:] == ["hotels", "done"]
    cards = events[-2].data["cards"]
    assert [(c["name"], c["url"]) for c in cards] == [
        ("Mercure", "https://www.booking.com/hotel/vn/mercure.html"),
        ("The Light", "https://www.agoda.com/the-light"),
    ]
    assert "Mercure Hai Phong" in rig.provider.calls[1][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.content, last.suggestions) == (
        "hotel_options",
        "Giá tham khảo từ các trang đặt phòng.",
        cards,
    )
    row = db_conn.execute("SELECT DISTINCT kind, conversation_id FROM research_results").fetchall()
    assert row == [("accommodation", conversation.id)]


def test_hotel_question_without_hits_answers_in_text_only(db_pool, db_conn, conversation):
    search = FakeSearch(default=[])
    answer = hotel_answer("Mình chưa tìm được khách sạn nào trên các trang đặt phòng.")
    rig = Rig(db_pool, [route("hotel_options", "hotel"), answer], search)
    events = rig.say(conversation.id, HOTEL_QUESTION)

    assert "hotels" not in [e.type for e in events]
    assert "<search_results>\nnone\n</search_results>" in rig.provider.calls[1][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.suggestions) == ("hotel_options", None)


def test_hotel_cards_with_unknown_sources_only_give_no_slider(db_pool, db_conn, conversation):
    answer = hotel_answer("Some options.", {"name": "Made up", "source_id": 99})
    rig = Rig(db_pool, [route("hotel_options", "hotel"), answer], FakeSearch(default=HOTEL_HITS))
    events = rig.say(conversation.id, HOTEL_QUESTION)

    assert "hotels" not in [e.type for e in events]
    assert recent_messages(db_conn, conversation.id, 2)[-1].suggestions is None


def test_clarification_is_streamed_and_saved(db_pool, db_conn, conversation):
    ask = json.dumps(
        {
            "status": "needs_clarification",
            "architecture": None,
            "steps": [],
            "aggregation": None,
            "clarification": "Which day do you mean?",
            "reasoning": "unclear",
        }
    )
    rig = Rig(db_pool, [ask])
    events = rig.say(conversation.id, "move it")
    assert spoken(events) == "Which day do you mean?"
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "clarification"


def test_closing_stream_after_first_token_still_saves_assistant_message(
    db_pool, db_conn, conversation, ready_trip
):
    rig = Rig(db_pool, [route("plan_answer"), ANSWER])
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "Where?", ready_trip.id, 1)
    events = stream_reply(turn, rig.deps)
    first = next(events)
    events.close()
    assert first.type == "token"
    assert recent_messages(db_conn, conversation.id, 2)[-1].content == first.data["text"]


def test_closing_stream_after_an_applied_edit_keeps_the_plan_and_the_text_so_far(
    db_pool, db_conn, conversation, ready_trip
):
    rig = Rig(db_pool, [route("plan_editor"), RENAME])
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "Rename the walk", ready_trip.id, 1)
    events = stream_reply(turn, rig.deps)
    plan_event = next(events)
    first = next(events)
    events.close()

    assert (plan_event.type, first.type) == ("plan", "token")
    assert get_trip(db_conn, ready_trip.id).plan_revision == 2
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.role, last.content, last.intent) == (
        "assistant",
        first.data["text"],
        "plan_editor",
    )


# A provider that notes how many pool connections are checked out whenever it is called
class Watcher(FakeProvider):
    def __init__(self, script: Sequence[str | Exception], pool: ConnectionPool) -> None:
        super().__init__(script)
        self.pool = pool
        self.busy: list[int] = []

    # Count the checked-out connections, then answer as the script says
    def _next(self, messages: Any, system_prompt: str) -> str:
        self.busy.append(checked_out(self.pool))
        return super()._next(messages, system_prompt)


# Connections of the pool that are in use right now
def checked_out(pool: ConnectionPool) -> int:
    stats = pool.get_stats()
    return int(stats["pool_size"] - stats["pool_available"])


def test_no_database_connection_is_held_while_waiting_for_the_model(
    db_pool, db_conn, conversation, ready_trip
):
    db_pool.wait()
    watcher = Watcher([route("plan_answer"), ANSWER], db_pool)
    rig = Rig(db_pool, [], provider=watcher)
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "Where?", ready_trip.id, 1)
    between_events = [checked_out(db_pool) for _ in stream_reply(turn, rig.deps)]

    assert len(watcher.busy) == 2
    assert set(watcher.busy + between_events) == {0}


def test_quota_exhausted_yields_error_event(db_pool, conversation):
    rig = Rig(db_pool, [])
    assert isinstance(rig.sink, FakeSink)
    rig.sink.blocks["openrouter"] = (NOW + timedelta(hours=5), "daily cap")
    events = rig.say(conversation.id, "hello there")
    assert [e.type for e in events] == ["error", "done"]
    assert events[0].data["code"] == "quota_exhausted"
    assert events[0].data["blocked_until"] == (NOW + timedelta(hours=5)).isoformat()


def test_model_failure_yields_llm_unavailable_error_event(db_pool, conversation):
    rig = Rig(db_pool, [httpx.ConnectError("down")])
    events = rig.say(conversation.id, "hello there")
    assert [e.data.get("code") for e in events if e.type == "error"] == ["llm_unavailable"]


def test_to_sse_writes_event_and_json_data():
    event = ChatEvent("token", {"text": "Đà Lạt"})
    assert to_sse(event) == 'event: token\ndata: {"text": "Đà Lạt"}\n\n'


def test_unknown_conversation_raises_not_found(db_pool):
    with db_pool.connection() as conn, pytest.raises(NotFound):
        prepare_message(conn, uuid4(), "hi", None, None)
