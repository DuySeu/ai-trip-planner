from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from psycopg_pool import ConnectionPool

from core.constants import ModelId
from core.exceptions import Conflict, InvalidInput, NotFound, PlanConflict
from core.settings import load_settings
from db.call_sink import DbCallSink
from db.repositories.conversations import create_conversation, get_conversation, save_draft
from db.repositories.jobs import active_job, enqueue
from db.repositories.messages import add_message, get_message, recent_messages
from db.repositories.research import sources_for_trip
from db.repositories.trips import TripRow, create_trip, get_trip, save_plan
from db.repositories.users import UserRow, claim_user
from domain.booking import BookingDates
from models.llm_factory import ProviderCallError
from models.model_router import ModelRouter
from orchestration.events import ChatEvent, to_sse
from orchestration.guard_turn import GUARDRAIL_CONFIG as GUARDRAIL
from orchestration.guard_turn import OFF_TOPIC
from orchestration.orchestrator import ChatDeps, stream_reply
from orchestration.state_manager import FollowUp, prepare_message
from service.tavily.search import SearchHit
from tests.fakes import FakeProvider, FakeSearch, FakeSink
from tests.fixtures.builders import DALAT_FIELDS, dalat_plan

MODEL = ModelId.LING_3_2_FLASH
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
PURPOSES = ("classify", "edit", "repair", "answer", "discover", "suggest", "guard")
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
        guardrail: Mapping[str, Any] | None = None,
        chat_choices: frozenset[str] = frozenset(),
    ) -> None:
        self.provider = provider or FakeProvider(script)
        self.sink = sink or FakeSink()
        self.search = search or FakeSearch(default=HITS)
        self.pool = pool
        router = ModelRouter(
            llm=self.provider,
            models={purpose: [MODEL] for purpose in PURPOSES},  # type: ignore[misc]
            sink=self.sink,
            reset_hour_utc=0,
            now=lambda: NOW,
            chat_choices=chat_choices,
        )
        self.deps = ChatDeps(
            pool,
            router,
            self.search,
            load_settings(ENV),
            lambda: NOW,
            lambda q, language: [],
            guardrail,
        )
        self.router = router

    # Save the visitor's message and stream the reply to the end
    def say(
        self,
        conversation_id: Any,
        content: str,
        trip: TripRow | None = None,
        revision: int | None = None,
        follow_up: FollowUp | None = None,
        default_origin: str | None = None,
    ) -> list[ChatEvent]:
        with self.pool.connection() as conn:
            turn = prepare_message(
                conn,
                conversation_id,
                content,
                trip.id if trip else None,
                revision,
                follow_up=follow_up,
                today=NOW.date(),
                default_origin=default_origin,
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
    trip = create_trip(db_conn, user.id, DALAT_FIELDS, None)
    return save_plan(
        db_conn, trip.id, 0, dalat_plan().model_dump(mode="json"), Decimal("1000000"), False, "m"
    )


# The text of the token events, joined
def spoken(events: Sequence[ChatEvent]) -> str:
    return "".join(e.data["text"] for e in events if e.type == "token")


def test_question_streams_answer_and_saves_both_messages(
    db_pool, db_conn, conversation, ready_trip
):
    rig = Rig(db_pool, [route("advice"), ANSWER])
    events = rig.say(conversation.id, "Where is the stay?", ready_trip, ready_trip.plan_revision)

    assert spoken(events) == ANSWER
    assert events[-1] == ChatEvent("done", {})
    saved = recent_messages(db_conn, conversation.id, 5)
    assert [(m.role, m.content, m.intent) for m in saved] == [
        ("user", "Where is the stay?", None),
        ("assistant", ANSWER, "advice"),
    ]
    assert saved[-1].metadata is None
    # The answer call saw the plan with its ids and the question
    content = rig.provider.calls[1][0][0]["content"]
    assert "it_3" in content and "Where is the stay?" in content


def test_chat_turn_calls_the_conversations_model_first(db_pool, db_conn, user):
    chosen = ModelId.PARTICLE_1
    conversation = create_conversation(db_conn, user.id, None, chosen)
    rig = Rig(db_pool, [route("advice"), ANSWER], chat_choices=frozenset({MODEL, chosen}))
    assert spoken(rig.say(conversation.id, "What should I pack for Sapa?")) == ANSWER
    # The classifier keeps CLASSIFIER_MODELS; the answer goes to the chosen model
    assert rig.provider.models == [MODEL, chosen]


def test_question_without_open_trip_gets_travel_advice(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [route("advice"), "Bring a light jacket."])
    events = rig.say(conversation.id, "What should I pack for Sapa?")
    assert spoken(events) == "Bring a light jacket."
    assert "<plan>" not in rig.provider.calls[1][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.metadata) == ("advice", None)


def test_unknown_agent_from_router_falls_back_to_advice(db_pool, db_conn, conversation, caplog):
    # An agent of the old catalog fails the check, the repair names it again, the router gives up
    old = route("discover_ask")
    rig = Rig(db_pool, [old, old, "Try Hue in spring."])
    with caplog.at_level(logging.INFO, logger="orchestration.orchestrator"):
        events = rig.say(conversation.id, "Where should I go?")
    assert spoken(events) == "Try Hue in spring."
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "advice"
    assert "chat flow: advice (classifier picked none, fallback)" in caplog.text


def test_routing_logs_the_chosen_flow_and_the_reason(db_pool, conversation, caplog):
    rig = Rig(db_pool, [route("web_lookup"), "Bring a light jacket."])
    with caplog.at_level(logging.INFO, logger="orchestration.orchestrator"):
        rig.say(conversation.id, "What should I pack for Sapa?")
    assert "chat flow: web_lookup (classifier picked web_lookup, routed): fits" in caplog.text


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
    queued = create_trip(db_conn, user.id, DALAT_FIELDS, None)
    with db_pool.connection() as conn, pytest.raises(Conflict):
        prepare_message(conn, conversation.id, "hi", queued.id, None)


def test_prepare_message_uses_hanoi_when_no_default_origin(db_pool, conversation):
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "hi", None, None)
    assert turn.default_origin == "Hà Nội"


def test_prepare_message_keeps_sent_default_origin(db_pool, conversation):
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "hi", None, None, default_origin="Đà Nẵng")
    assert turn.default_origin == "Đà Nẵng"


def test_default_origin_is_not_saved_into_draft(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    # The model writes the default back as the origin it searched from
    rig = Rig(db_pool, [route("flight_search", "flights to Hue"), flight_answer("Đà Nẵng")])
    rig.say(conversation.id, "Flights to Hue?", default_origin="Đà Nẵng")
    assert get_conversation(db_conn, conversation.id).request_draft == DRAFT_DATES


def test_edit_without_open_trip_asks_to_open_it(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [route("edit_plan")])
    events = rig.say(conversation.id, "Move lunch to 13:00")
    assert "Open the trip" in spoken(events)
    assert len(rig.provider.calls) == 1
    assert recent_messages(db_conn, conversation.id, 2)[-1].intent == "edit_plan"


def test_edit_without_open_trip_answers_a_vietnamese_message_in_vietnamese(db_pool, conversation):
    rig = Rig(db_pool, [route("edit_plan")])
    events = rig.say(conversation.id, "Đổi bữa trưa sang 13:00")
    assert "Hãy mở chuyến đi" in spoken(events)


def test_llm_calls_carry_the_user_message_id(db_pool, db_conn, conversation, ready_trip):
    rig = Rig(db_pool, [route("advice"), ANSWER], sink=DbCallSink(db_pool))
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
    rig = Rig(db_pool, [route("edit_plan"), RENAME])
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
    rig = Rig(db_pool, [route("edit_plan"), bad, bad])
    events = rig.say(conversation.id, "Drop it_999", ready_trip, ready_trip.plan_revision)
    assert [e.type for e in events] == ["token"] * (len(events) - 1) + ["done"]
    assert "could not turn that" in spoken(events)
    assert get_trip(db_conn, ready_trip.id).plan_revision == ready_trip.plan_revision


def test_edit_while_job_active_yields_conflict_error_event(
    db_pool, db_conn, conversation, ready_trip
):
    enqueue(db_conn, ready_trip.id)
    rig = Rig(db_pool, [route("edit_plan")])
    events = rig.say(conversation.id, "Rename the walk", ready_trip, ready_trip.plan_revision)
    assert [e.type for e in events] == ["error", "done"]
    assert events[0].data["code"] == "conflict"
    assert len(rig.provider.calls) == 1
    assert get_trip(db_conn, ready_trip.id).plan_revision == ready_trip.plan_revision
    assert [m.role for m in recent_messages(db_conn, conversation.id, 5)] == ["user"]


def test_update_request_queues_replan_job(db_pool, db_conn, conversation, ready_trip):
    rig = Rig(db_pool, [route("edit_plan"), CHANGE_TRAVELERS])
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
    rig = Rig(db_pool, [route("edit_plan"), early])
    events = rig.say(conversation.id, "Go in January", ready_trip, ready_trip.plan_revision)
    assert "cannot make that change" in spoken(events)
    assert active_job(db_conn, ready_trip.id) is None


def test_research_searches_once_with_router_task_text(db_pool, db_conn, conversation, ready_trip):
    task = "train or bus Da Lat to Nha Trang, 4 people, 21 Dec"
    rig = Rig(db_pool, [route("web_lookup", task), "The night bus costs about 350000 VND."])
    events = rig.say(conversation.id, "Bus or train to Nha Trang?", ready_trip, 1)

    assert rig.search.calls == [task]
    assert rig.search.tasks == ["chat"]
    assert "350000" in spoken(events)
    saved = [s for s in sources_for_trip(db_conn, ready_trip.id) if s.kind == "chat"]
    assert [(s.title, s.url) for s in saved] == [("Train guide", "https://example.com/t")]
    assert "Train guide" in rig.provider.calls[1][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.metadata) == ("advice", {"searched": True})


def test_research_searches_again_only_when_first_search_is_empty(db_pool, conversation):
    search = FakeSearch({"cheap stay": []}, default=HITS)
    rig = Rig(db_pool, [route("web_lookup", "cheap stay"), "Try the old town."], search)
    rig.say(conversation.id, "Cheap stay?")
    assert search.calls == ["cheap stay", "cheap stay travel guide"]


def test_research_without_trip_keeps_hits_on_the_conversation(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [route("web_lookup", "visa for Japan"), "Check the embassy."])
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


DRAFT_DATES = {"start_date": "2026-12-20", "end_date": "2026-12-23"}
STAY = {"check_in": "2026-12-20", "check_out": "2026-12-23"}


def test_hotel_question_with_dates_streams_cards_in_a_metadata_event(
    db_pool, db_conn, conversation
):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
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
    rig = Rig(db_pool, [route("hotel_search", task), answer], search)
    events = rig.say(conversation.id, HOTEL_QUESTION)

    assert (search.calls, search.tasks) == ([f"{task} 12/2026"], ["accommodation"])
    assert spoken(events) == "Giá tham khảo từ các trang đặt phòng."
    assert [e.type for e in events][-2:] == ["metadata", "done"]
    assert events[-2].data["message_id"] is None
    meta = events[-2].data["metadata"]
    assert [(c["name"], c["url"]) for c in meta["cards"]] == [
        ("Mercure", "https://www.booking.com/hotel/vn/mercure.html"),
        ("The Light", "https://www.agoda.com/the-light"),
    ]
    assert (meta["kind"], meta["status"], meta["query"], meta["dates"]) == (
        "hotel",
        "results",
        task,
        STAY,
    )
    prompt = rig.provider.calls[1][0][0]["content"]
    assert "Mercure Hai Phong" in prompt and "check-in 2026-12-20" in prompt
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.content, last.metadata) == (
        "booking_search",
        "Giá tham khảo từ các trang đặt phòng.",
        meta,
    )
    row = db_conn.execute("SELECT DISTINCT kind, conversation_id FROM research_results").fetchall()
    assert row == [("accommodation", conversation.id)]


def test_hotel_question_takes_the_open_trip_dates(db_pool, db_conn, conversation, ready_trip):
    answer = hotel_answer("Some options.", {"name": "Mercure", "source_id": 1})
    rig = Rig(db_pool, [route("hotel_search", "hotel"), answer], FakeSearch(default=HOTEL_HITS))
    events = rig.say(conversation.id, HOTEL_QUESTION, ready_trip, ready_trip.plan_revision)
    assert events[-2].data["metadata"]["dates"] == STAY


def test_hotel_question_without_hits_saves_empty_cards(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    search = FakeSearch(default=[])
    answer = hotel_answer("Mình chưa tìm được khách sạn nào trên các trang đặt phòng.")
    rig = Rig(db_pool, [route("hotel_search", "hotel"), answer], search)
    events = rig.say(conversation.id, HOTEL_QUESTION)

    assert events[-2].data["metadata"]["cards"] == []
    assert "<search_results>\nnone\n</search_results>" in rig.provider.calls[1][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert last.intent == "booking_search"
    assert last.metadata is not None and last.metadata["cards"] == []


def test_hotel_cards_with_unknown_sources_only_give_no_cards(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    answer = hotel_answer("Some options.", {"name": "Made up", "source_id": 99})
    rig = Rig(db_pool, [route("hotel_search", "hotel"), answer], FakeSearch(default=HOTEL_HITS))
    rig.say(conversation.id, HOTEL_QUESTION)
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert last.metadata is not None and last.metadata["cards"] == []


def test_hotel_question_with_dates_in_the_message_searches_without_a_card(
    db_pool, db_conn, conversation
):
    search = FakeSearch(default=HOTEL_HITS)
    answer = hotel_answer("Some options.", {"name": "Mercure", "source_id": 1})
    rig = Rig(db_pool, [route("hotel_search", "khách sạn Hải Phòng giá"), answer], search)
    events = rig.say(conversation.id, "Khách sạn Hải Phòng ngày 20/12 đến 23/12 giá bao nhiêu?")

    assert search.calls == ["khách sạn Hải Phòng giá 12/2026"]
    assert events[-2].data["metadata"]["dates"] == STAY
    assert get_conversation(db_conn, conversation.id).request_draft == DRAFT_DATES


def test_hotel_question_with_past_draft_dates_asks_for_new_dates(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {"start_date": "2026-11-01", "end_date": "2026-11-03"})
    search = FakeSearch(default=HOTEL_HITS)
    rig = Rig(db_pool, [route("hotel_search", "hotel Hai Phong")], search)
    rig.say(conversation.id, HOTEL_QUESTION)
    assert search.calls == []
    card = recent_messages(db_conn, conversation.id, 1)[-1]
    assert card.metadata is not None and card.metadata["status"] == "need_dates"


def test_hotel_question_without_dates_saves_a_need_dates_card(db_pool, db_conn, conversation):
    search = FakeSearch(default=HOTEL_HITS)
    rig = Rig(db_pool, [route("hotel_search", "khách sạn Hải Phòng")], search)
    events = rig.say(conversation.id, HOTEL_QUESTION)

    assert search.calls == [] and len(rig.provider.calls) == 1
    card = recent_messages(db_conn, conversation.id, 1)[-1]
    assert card.intent == "booking_search"
    assert card.metadata == {
        "kind": "hotel",
        "status": "need_dates",
        "query": "khách sạn Hải Phòng",
    }
    assert spoken(events) == card.content == "Bạn định nhận phòng và trả phòng ngày nào?"
    assert [e.type for e in events][-2:] == ["metadata", "done"]
    assert events[-2].data == {"message_id": str(card.id), "metadata": card.metadata}


# A booking card waiting for dates, as the router turn saves it
def need_dates(db_conn, conversation, kind: str = "hotel", query: str = "hotel Hai Phong") -> Any:
    meta = {"kind": kind, "status": "need_dates", "query": query}
    return add_message(
        db_conn, conversation.id, "assistant", "Which dates?", "booking_search", meta
    )


def test_booking_follow_up_searches_with_the_chosen_dates_and_closes_the_card(
    db_pool, db_conn, conversation
):
    card = need_dates(db_conn, conversation)
    answer = hotel_answer("Prices from booking sites.", {"name": "Mercure", "source_id": 1})
    search = FakeSearch(default=HOTEL_HITS)
    rig = Rig(db_pool, [answer], search)
    dates = BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 23))
    events = rig.say(
        conversation.id, "Search with these dates", follow_up=FollowUp(card.id, "booking", dates)
    )

    assert len(rig.provider.calls) == 1  # no router call
    assert search.calls == ["hotel Hai Phong 12/2026"]
    assert "check-in 2026-12-20" in rig.provider.calls[0][0][0]["content"]
    assert get_message(db_conn, card.id).metadata == {
        "kind": "hotel",
        "status": "done",
        "query": "hotel Hai Phong",
    }
    last = recent_messages(db_conn, conversation.id, 1)[-1]
    assert last.metadata is not None
    assert (last.metadata["status"], last.metadata["dates"]) == ("results", STAY)
    assert [c["name"] for c in events[-2].data["metadata"]["cards"]] == ["Mercure"]
    assert get_conversation(db_conn, conversation.id).request_draft == DRAFT_DATES


def test_booking_follow_up_keeps_dates_the_draft_already_has(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {"start_date": "2027-01-05", "origin": "Huế"})
    card = need_dates(db_conn, conversation)
    rig = Rig(db_pool, [hotel_answer("Ok.")], FakeSearch(default=[]))
    dates = BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 23))
    rig.say(conversation.id, "Search", follow_up=FollowUp(card.id, "booking", dates))
    draft = get_conversation(db_conn, conversation.id).request_draft
    assert draft == {"start_date": "2027-01-05", "origin": "Huế"}


@pytest.mark.parametrize(
    ("check_in", "check_out"),
    [
        (date(2026, 11, 16), date(2026, 11, 20)),  # in the past
        (date(2026, 12, 20), date(2026, 12, 20)),  # check-out not after check-in
        (date(2026, 12, 1), date(2027, 1, 1)),  # 31 nights
    ],
)
def test_booking_follow_up_with_bad_dates_is_rejected_before_search(
    db_pool, db_conn, conversation, check_in, check_out
):
    card = need_dates(db_conn, conversation)
    rig = Rig(db_pool, [], FakeSearch(default=HOTEL_HITS))
    dates = BookingDates(check_in=check_in, check_out=check_out)
    with pytest.raises(InvalidInput):
        rig.say(conversation.id, "Search", follow_up=FollowUp(card.id, "booking", dates))
    assert rig.search.calls == []
    meta = get_message(db_conn, card.id).metadata
    assert meta is not None and meta["status"] == "need_dates"
    assert recent_messages(db_conn, conversation.id, 1)[-1].id == card.id


def test_second_booking_follow_up_on_the_same_card_conflicts(db_pool, db_conn, conversation):
    card = need_dates(db_conn, conversation)
    rig = Rig(db_pool, [hotel_answer("Ok.")], FakeSearch(default=[]))
    follow_up = FollowUp(
        card.id, "booking", BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 22))
    )
    rig.say(conversation.id, "Search", follow_up=follow_up)
    with pytest.raises(Conflict):
        rig.say(conversation.id, "Search", follow_up=follow_up)


def test_booking_follow_up_closes_the_card_before_the_stream_so_a_second_press_saves_nothing(
    db_pool, db_conn, conversation
):
    card = need_dates(db_conn, conversation)
    follow_up = FollowUp(
        card.id, "booking", BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 22))
    )
    with db_pool.connection() as conn:
        prepare_message(
            conn, conversation.id, "Search", None, None, follow_up=follow_up, today=NOW.date()
        )
    meta = get_message(db_conn, card.id).metadata
    assert meta is not None and meta["status"] == "done"
    with db_pool.connection() as conn, pytest.raises(Conflict):
        prepare_message(
            conn, conversation.id, "Search", None, None, follow_up=follow_up, today=NOW.date()
        )
    roles = [m.role for m in recent_messages(db_conn, conversation.id, 5)]
    assert roles == ["assistant", "user"]


def test_booking_follow_up_reopens_the_card_when_the_model_fails(db_pool, db_conn, conversation):
    card = need_dates(db_conn, conversation)
    rig = Rig(
        db_pool, [ProviderCallError("provider_error", "ConnectError: down")], FakeSearch(default=[])
    )
    dates = BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 22))
    events = rig.say(conversation.id, "Search", follow_up=FollowUp(card.id, "booking", dates))
    assert [e.data.get("code") for e in events if e.type == "error"] == ["llm_unavailable"]
    assert get_message(db_conn, card.id).metadata == card.metadata


def test_booking_follow_up_on_a_questionnaire_conflicts(db_pool, db_conn, conversation):
    card = add_message(
        db_conn,
        conversation.id,
        "assistant",
        "",
        "discover",
        {"kind": "questionnaire", "status": "open", "step": 0, "answers": {}, "choices": {}},
    )
    dates = BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 22))
    with pytest.raises(Conflict):
        Rig(db_pool, []).say(
            conversation.id, "Search", follow_up=FollowUp(card.id, "booking", dates)
        )


FLIGHT_HITS = [
    SearchHit("Vietjet Hà Nội Đà Nẵng", "https://www.traveloka.com/vj", "From 890,000 VND"),
    SearchHit("Vietnam Airlines HAN-DAD", "https://www.skyscanner.com/vn", "Daily flights"),
]


def test_flight_question_searches_transport_sites_and_streams_flight_cards(
    db_pool, db_conn, conversation
):
    save_draft(db_conn, conversation.id, {**DRAFT_DATES, "origin": "Hà Nội"})
    task = "vé máy bay Hà Nội Đà Nẵng giá"
    answer = json.dumps(
        {
            "reply": "Vé tham khảo từ các trang bán vé.",
            "cards": [
                {"carrier": "Vietnam Airlines", "route": "Hà Nội - Đà Nẵng", "source_id": 2},
                {
                    "carrier": "Vietjet",
                    "route": "Hà Nội - Đà Nẵng",
                    "price_from": "890000",
                    "source_id": 1,
                },
                {"carrier": "Made up", "route": "x - y", "source_id": 99},
            ],
        }
    )
    search = FakeSearch(default=FLIGHT_HITS)
    rig = Rig(db_pool, [route("flight_search", task), answer], search)
    events = rig.say(conversation.id, "vé máy bay Hà Nội đi Đà Nẵng bao nhiêu")

    assert (search.calls, search.tasks) == ([f"{task} 12/2026"], ["transport"])
    assert (
        "depart 2026-12-20, return 2026-12-23, known origin Hà Nội"
        in rig.provider.calls[1][0][0]["content"]
    )
    meta = events[-2].data["metadata"]
    assert (meta["kind"], meta["status"], meta["dates"]) == (
        "flight",
        "results",
        {"depart": "2026-12-20", "return": "2026-12-23"},
    )
    assert [(c["carrier"], c["url"]) for c in meta["cards"]] == [
        ("Vietjet", "https://www.traveloka.com/vj"),
        ("Vietnam Airlines", "https://www.skyscanner.com/vn"),
    ]
    rows = db_conn.execute("SELECT DISTINCT kind FROM research_results").fetchall()
    assert rows == [("transport",)]
    assert recent_messages(db_conn, conversation.id, 1)[-1].metadata == meta


# A flight answer with no cards; origin is the one the model says it searched for
def flight_answer(origin: str | None = None) -> str:
    return json.dumps({"reply": "Ok.", "cards": [], "origin": origin})


def test_flight_question_without_origin_searches_from_default_origin(
    db_pool, db_conn, conversation
):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    rig = Rig(
        db_pool,
        [route("flight_search", "flights to Da Nang"), flight_answer()],
        FakeSearch(default=FLIGHT_HITS),
    )
    events = rig.say(conversation.id, "Flights to Da Nang?")
    assert rig.search.calls == ["flights to Da Nang 12/2026"]
    assert "known origin Hà Nội" in rig.provider.calls[1][0][0]["content"]
    assert events[-2].data["metadata"]["status"] == "results"
    assert "origin" not in get_conversation(db_conn, conversation.id).request_draft


def test_flight_question_uses_sent_default_origin(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    rig = Rig(db_pool, [route("flight_search", "flights to Hue"), flight_answer()])
    rig.say(conversation.id, "Flights to Hue?", default_origin="Đà Nẵng")
    assert "known origin Đà Nẵng" in rig.provider.calls[1][0][0]["content"]


def test_flight_draft_origin_wins_over_default_origin(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {**DRAFT_DATES, "origin": "Huế"})
    rig = Rig(db_pool, [route("flight_search", "flights to Hanoi"), flight_answer()])
    rig.say(conversation.id, "Flights to Hanoi?", default_origin="Đà Nẵng")
    content = rig.provider.calls[1][0][0]["content"]
    assert "known origin Huế" in content
    assert "Đà Nẵng" not in content


def test_flight_origin_named_in_message_is_saved_to_draft(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    rig = Rig(db_pool, [route("flight_search", "vé Huế Đà Nẵng"), flight_answer("Huế")])
    rig.say(conversation.id, "vé từ Huế đi Đà Nẵng")
    assert get_conversation(db_conn, conversation.id).request_draft == {
        **DRAFT_DATES,
        "origin": "Huế",
    }


@pytest.mark.parametrize("answered", [" hà nội ", "Hà Nội", "", None])
def test_flight_origin_equal_to_given_one_or_empty_is_not_saved(
    db_pool, db_conn, conversation, answered
):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    rig = Rig(db_pool, [route("flight_search", "flights to Da Nang"), flight_answer(answered)])
    rig.say(conversation.id, "Flights to Da Nang?")
    assert get_conversation(db_conn, conversation.id).request_draft == DRAFT_DATES


@pytest.mark.parametrize(
    ("message", "answered"),
    [("Flights to Da Nang?", "Hanoi"), ("Vé đi Đà Nẵng?", "Thành phố Hồ Chí Minh")],
)
def test_flight_origin_not_in_the_message_is_not_saved(
    db_pool, db_conn, conversation, message, answered
):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    rig = Rig(db_pool, [route("flight_search", "flights to Da Nang"), flight_answer(answered)])
    rig.say(conversation.id, message, default_origin="TP. Hồ Chí Minh")
    assert get_conversation(db_conn, conversation.id).request_draft == DRAFT_DATES


def test_flight_origin_named_without_accents_is_saved(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, DRAFT_DATES)
    rig = Rig(db_pool, [route("flight_search", "flights Hue Da Nang"), flight_answer("Huế")])
    rig.say(conversation.id, "flights from HUE to Da Nang")
    assert get_conversation(db_conn, conversation.id).request_draft["origin"] == "Huế"


def test_flight_follow_up_without_origin_uses_default_and_saves_none(
    db_pool, db_conn, conversation
):
    card = need_dates(db_conn, conversation, "flight", "flights to Da Nang")
    dates = BookingDates(depart=date(2026, 12, 20))
    rig = Rig(db_pool, [flight_answer()], FakeSearch(default=[]))
    rig.say(
        conversation.id,
        "Search",
        follow_up=FollowUp(card.id, "booking", dates),
        default_origin="Đà Nẵng",
    )
    assert get_conversation(db_conn, conversation.id).request_draft == {"start_date": "2026-12-20"}
    assert "known origin Đà Nẵng" in rig.provider.calls[0][0][0]["content"]


def test_flight_follow_up_takes_the_card_origin_into_the_draft(db_pool, db_conn, conversation):
    card = need_dates(db_conn, conversation, "flight", "flights to Da Nang")
    dates = BookingDates(depart=date(2026, 12, 20))
    rig = Rig(db_pool, [flight_answer()], FakeSearch(default=[]))
    rig.say(conversation.id, "Search", follow_up=FollowUp(card.id, "booking", dates, "Huế"))
    assert get_conversation(db_conn, conversation.id).request_draft == {
        "start_date": "2026-12-20",
        "origin": "Huế",
    }
    assert "known origin Huế" in rig.provider.calls[0][0][0]["content"]


def test_router_clarification_is_advice_with_clarify_flag(db_pool, db_conn, conversation):
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
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.metadata) == ("advice", {"clarify": True})


def test_closing_stream_after_first_token_still_saves_assistant_message(
    db_pool, db_conn, conversation, ready_trip
):
    rig = Rig(db_pool, [route("advice"), ANSWER])
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
    rig = Rig(db_pool, [route("edit_plan"), RENAME])
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
        "edit_plan",
    )


# A provider that notes how many pool connections are checked out whenever it is called
class Watcher(FakeProvider):
    def __init__(self, script: Sequence[str | Exception], pool: ConnectionPool) -> None:
        super().__init__(script)
        self.pool = pool
        self.busy: list[int] = []

    # Count the checked-out connections, then answer as the script says
    def _next(
        self, model_id: str, messages: Any, system_prompt: str, timeout_s: float | None
    ) -> str:
        self.busy.append(checked_out(self.pool))
        return super()._next(model_id, messages, system_prompt, timeout_s)


# Connections of the pool that are in use right now
def checked_out(pool: ConnectionPool) -> int:
    stats = pool.get_stats()
    return int(stats["pool_size"] - stats["pool_available"])


def test_no_database_connection_is_held_while_waiting_for_the_model(
    db_pool, db_conn, conversation, ready_trip
):
    db_pool.wait()
    watcher = Watcher([route("advice"), ANSWER], db_pool)
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
    rig = Rig(db_pool, [ProviderCallError("provider_error", "ConnectError: down")])
    events = rig.say(conversation.id, "hello there")
    assert [e.data.get("code") for e in events if e.type == "error"] == ["llm_unavailable"]


def test_to_sse_writes_event_and_json_data():
    event = ChatEvent("token", {"text": "Đà Lạt"})
    assert to_sse(event) == 'event: token\ndata: {"text": "Đà Lạt"}\n\n'


def test_unknown_conversation_raises_not_found(db_pool):
    with db_pool.connection() as conn, pytest.raises(NotFound):
        prepare_message(conn, uuid4(), "hi", None, None)


# The topic judge's JSON verdict
def judge(score: float, category: str | None = None) -> str:
    return json.dumps({"score": score, "category": category, "reason": "r"})


def test_off_topic_message_is_blocked_before_the_router(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [judge(0.95, "off_topic")], sink=DbCallSink(db_pool), guardrail=GUARDRAIL)
    events = rig.say(conversation.id, "Write a Python function that sorts a list")

    assert spoken(events) == OFF_TOPIC[0]
    assert len(rig.provider.calls) == 1  # the judge only, no router call
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.metadata) == (
        "advice",
        {"blocked": True, "guard": "travel_only", "category": "off_topic"},
    )
    purposes = db_conn.execute("SELECT purpose FROM llm_calls").fetchall()
    assert purposes == [("guard",)]


def test_travel_question_passes_the_guard_and_is_routed(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [judge(0.02), route("advice"), "Bring a light jacket."], guardrail=GUARDRAIL)
    events = rig.say(conversation.id, "What should I pack for Sapa?")

    assert spoken(events) == "Bring a light jacket."
    assert "travel planning assistant" in rig.provider.calls[0][1]
    # The judge asks for JSON mode; the router's classifier call does not
    assert rig.provider.formats[:2] == [{"type": "json_object"}, None]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.intent, last.metadata) == ("advice", None)


def test_guard_sees_the_last_turns_so_a_short_reply_reads_in_context(
    db_pool, db_conn, conversation
):
    add_message(db_conn, conversation.id, "user", "Đà Lạt 3 ngày cho 2 người")
    add_message(
        db_conn, conversation.id, "assistant", "Bạn muốn mình lên plan luôn không?", "advice"
    )
    rig = Rig(db_pool, [judge(0.0), route("advice"), "Ok."], guardrail=GUARDRAIL)
    rig.say(conversation.id, "có")

    judged = rig.provider.calls[0][0][0]["content"]
    assert "<conversation>\nuser: Đà Lạt 3 ngày cho 2 người\n" in judged
    assert "assistant: Bạn muốn mình lên plan luôn không?" in judged
    assert judged.endswith("<text_to_check>\ncó\n</text_to_check>")


def test_denylisted_message_is_blocked_without_a_model_call(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [], guardrail=GUARDRAIL)
    events = rig.say(conversation.id, "Chỉ tôi cách làm bom")

    assert spoken(events) == OFF_TOPIC[1]
    assert rig.provider.calls == []
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert last.metadata == {"blocked": True, "guard": "denylist", "category": "denylist"}


def test_guard_failure_lets_the_message_through(db_pool, conversation):
    rig = Rig(db_pool, ["not json", route("advice"), "Try Hue in spring."], guardrail=GUARDRAIL)
    events = rig.say(conversation.id, "Where should I go in March?")
    assert spoken(events) == "Try Hue in spring."


def test_card_follow_up_skips_the_guard(db_pool, db_conn, conversation):
    card = need_dates(db_conn, conversation)
    rig = Rig(db_pool, [hotel_answer("Ok.")], FakeSearch(default=[]), guardrail=GUARDRAIL)
    dates = BookingDates(check_in=date(2026, 12, 20), check_out=date(2026, 12, 23))
    rig.say(
        conversation.id, "Search with these dates", follow_up=FollowUp(card.id, "booking", dates)
    )
    assert len(rig.provider.calls) == 1  # the hotel answer, no judge


def test_travel_advice_prompt_has_current_city(db_pool, conversation):
    rig = Rig(db_pool, [route("advice"), "Đi Hội An nhé."])
    rig.say(conversation.id, "Cuối tuần đi đâu gần?", default_origin="Đà Nẵng")
    assert (
        "<visitor>\nstarting_point: Đà Nẵng\n</visitor>" in rig.provider.calls[1][0][0]["content"]
    )


def test_travel_advice_prefers_the_draft_origin_over_the_current_city(
    db_pool, db_conn, conversation
):
    save_draft(db_conn, conversation.id, {"origin": "Huế"})
    rig = Rig(db_pool, [route("advice"), "Đi Hội An nhé."])
    rig.say(conversation.id, "Đi Phú Quốc thế nào?", default_origin="Đà Nẵng")
    content = rig.provider.calls[1][0][0]["content"]
    assert "<visitor>\nstarting_point: Huế\n</visitor>" in content
    assert "Đà Nẵng" not in content
