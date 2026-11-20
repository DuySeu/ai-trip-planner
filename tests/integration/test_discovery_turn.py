from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from chat.chat_service import ChatDeps, ChatTurn
from chat.discovery_turn import MAX_QUERIES, Action, discovery_queries, run_discovery_turn
from chat.events import ChatEvent
from core.constants import ModelId
from core.exceptions import InvalidLLMOutput, ResearchFailed
from core.settings import load_settings
from db.repositories.conversations import create_conversation, get_conversation, save_draft
from db.repositories.messages import add_message, recent_messages
from db.repositories.users import claim_user
from domain.discovery import RequestDraft, merge_draft
from models.model_router import ModelRouter
from service.tavily.search import SearchHit
from tests.fakes import FakeProvider, FakeSearch, FakeSink

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
HITS = [
    SearchHit("Krabi in December", "https://example.com/krabi", "Krabi is dry in December."),
    SearchHit("Da Nang beaches", "https://example.com/danang", "Da Nang is cool in December."),
]


# The model's answer for an ask or answer turn
def reply_answer(reply: str, draft: dict[str, Any] | None = None) -> str:
    return json.dumps({"reply": reply, "request_draft": draft or {}})


# One destination card as the model writes it
def card(name: str, country: str, source_ids: Sequence[int] = ()) -> dict[str, Any]:
    return {
        "name": name,
        "country_code": country,
        "why": "Dry and quiet in December.",
        "length_days": 4,
        "est_cost_per_person_vnd": "9000000",
        "best_months": ["December"],
        "highlights": ["Beaches", "Seafood"],
        "source_ids": list(source_ids),
    }


# The model's answer for a suggest turn: the reply, the draft and the cards
def suggest_answer(reply: str, *cards: dict[str, Any], draft: dict[str, Any] | None = None) -> str:
    return json.dumps({"reply": reply, "request_draft": draft or {}, "cards": list(cards)})


# The deps, the provider script and the search double of one test
class Rig:
    def __init__(self, pool: ConnectionPool, script: Sequence[str], search: FakeSearch) -> None:
        self.provider = FakeProvider(script)
        self.search = search
        router = ModelRouter(
            provider_for=lambda model_id: self.provider,
            models={"discover": [MODEL], "suggest": [MODEL], "repair": [MODEL]},
            sink=FakeSink(),
            daily_cap_pattern="free-models-per-day",
            reset_hour_utc=0,
            now=lambda: NOW,
        )
        self.deps = ChatDeps(
            pool, router, search, load_settings(ENV), lambda: NOW, lambda q, language: []
        )


@pytest.fixture
def conversation(db_conn):
    return create_conversation(db_conn, claim_user(db_conn, "Duy").id, None)


# Save the visitor's message and return the turn the discovery service runs
def turn_for(db_conn, conversation, content: str) -> ChatTurn:
    message = add_message(db_conn, conversation.id, "user", content)
    return ChatTurn(conversation.id, conversation.user_id, message, None, None)


def run(rig: Rig, turn: ChatTurn, action: Action, query: str | None = None) -> list[ChatEvent]:
    return list(run_discovery_turn(turn, rig.deps, action, query))


def test_ask_turn_makes_one_call_and_saves_draft(db_pool, db_conn, conversation):
    reply = "Which month do you want to travel?"
    answer = reply_answer(reply, {"origin": "Hanoi", "travelers": 2})
    rig = Rig(db_pool, [answer], FakeSearch())
    events = run(rig, turn_for(db_conn, conversation, "Somewhere warm, no idea where"), "ask")

    assert "".join(e.data["text"] for e in events) == reply
    assert {e.type for e in events} == {"token"}
    assert len(rig.provider.calls) == 1 and rig.search.calls == []
    draft = get_conversation(db_conn, conversation.id).request_draft
    assert draft == {"origin": "Hanoi", "travelers": 2}
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.role, last.content, last.intent, last.suggestions) == (
        "assistant",
        reply,
        "ask",
        None,
    )


def test_ask_turn_keeps_what_the_conversation_already_knew(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {"origin": "Hanoi", "month": "December"})
    answer = reply_answer("Who travels?", {"origin": None, "travelers": 2})
    rig = Rig(db_pool, [answer], FakeSearch())
    run(rig, turn_for(db_conn, conversation, "ok"), "ask")
    draft = get_conversation(db_conn, conversation.id).request_draft
    assert draft == {"origin": "Hanoi", "month": "December", "travelers": 2}
    assert "Hanoi" in rig.provider.calls[0][0][0]["content"]


def test_suggest_turn_searches_then_streams_cards(db_pool, db_conn, conversation):
    search = FakeSearch({"warm beaches": HITS})
    script = [
        suggest_answer(
            "I assume two travelers.",
            card("Krabi", "TH", [1, 99]),
            card("Da Nang", "VN", [2]),
            draft={"month": "December"},
        )
    ]
    rig = Rig(db_pool, script, search)
    events = run(
        rig, turn_for(db_conn, conversation, "Warm beach in December"), "suggest", "warm beaches"
    )

    assert [e.type for e in events][-1] == "suggestions"
    assert events[-2].type == "token"
    cards = events[-1].data["cards"]
    assert [(c["name"], c["source_ids"]) for c in cards] == [("Krabi", [1]), ("Da Nang", [2])]
    assert cards[0]["est_cost_per_person_vnd"] == "9000000"
    assert search.calls[0] == "warm beaches"
    rows = db_conn.execute(
        "SELECT id, kind, trip_id, conversation_id, title FROM research_results ORDER BY id"
    ).fetchall()
    assert rows == [
        (1, "chat", None, conversation.id, "Krabi in December"),
        (2, "chat", None, conversation.id, "Da Nang beaches"),
    ]
    # The one call saw the saved sources by their ids
    assert 'id="1"' in rig.provider.calls[0][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert last.intent == "suggest" and last.suggestions == cards
    assert last.content == "I assume two travelers."
    assert get_conversation(db_conn, conversation.id).request_draft == {"month": "December"}


def test_suggest_turn_makes_one_ai_call_after_search(db_pool, db_conn, conversation):
    script = [suggest_answer("Ideas.", card("Krabi", "TH", [1]))]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    run(rig, turn_for(db_conn, conversation, "Ideas please"), "suggest")
    assert len(rig.provider.calls) == 1
    assert len(rig.search.calls) == MAX_QUERIES


def test_router_step_task_is_the_first_search_query(db_pool, db_conn, conversation):
    task = "quiet beach islands in December from Hanoi"
    rig = Rig(db_pool, [suggest_answer("Ideas.", card("Krabi", "TH"))], FakeSearch(default=HITS))
    run(rig, turn_for(db_conn, conversation, "Ideas please"), "suggest", task)
    fallback = discovery_queries(RequestDraft(), "en")
    assert rig.search.calls == [task, *fallback[:2]]
    assert set(rig.search.tasks) == {"discovery"}


def test_a_task_equal_to_a_drafted_query_is_searched_once(db_pool, db_conn, conversation):
    fallback = discovery_queries(RequestDraft(), "en")
    rig = Rig(db_pool, [suggest_answer("Ideas.", card("Krabi", "TH"))], FakeSearch(default=HITS))
    run(rig, turn_for(db_conn, conversation, "Ideas please"), "suggest", fallback[0])
    assert rig.search.calls == list(fallback)


def test_third_ask_is_turned_into_suggest(db_pool, db_conn, conversation):
    for _ in range(2):
        add_message(db_conn, conversation.id, "assistant", "Question?", "ask")
    save_draft(db_conn, conversation.id, {"origin": "Hanoi", "travel_styles": ["food"]})
    script = [suggest_answer("I assume a week.", card("Da Nang", "VN", [1]))]
    search = FakeSearch(default=HITS[:1])
    rig = Rig(db_pool, script, search)
    events = run(rig, turn_for(db_conn, conversation, "Just pick something"), "ask")

    assert events[-1].type == "suggestions"
    assert len(rig.provider.calls) == 1
    assert search.calls == list(
        discovery_queries(RequestDraft(origin="Hanoi", travel_styles=("food",)), "en")
    )
    assert recent_messages(db_conn, conversation.id, 1)[-1].intent == "suggest"


def test_card_with_unknown_country_is_dropped(db_pool, db_conn, conversation):
    script = [suggest_answer("Ideas.", card("Atlantis", "ZZ"), card("Krabi", "TH", [1]))]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    events = run(rig, turn_for(db_conn, conversation, "Ideas please"), "suggest")
    assert [c["name"] for c in events[-1].data["cards"]] == ["Krabi"]
    assert len(rig.provider.calls) == 1


def test_cards_without_any_supported_country_get_one_repair_round(db_pool, db_conn, conversation):
    script = [
        suggest_answer("Ideas.", card("Atlantis", "ZZ")),
        suggest_answer("Ideas.", card("Krabi", "TH")),
    ]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    events = run(rig, turn_for(db_conn, conversation, "Ideas please"), "suggest")
    assert [c["name"] for c in events[-1].data["cards"]] == ["Krabi"]
    assert "country_code" in rig.provider.calls[1][0][-1]["content"]


def test_a_failed_search_is_skipped_and_the_turn_goes_on(db_pool, db_conn, conversation):
    search = FakeSearch({"bad": ResearchFailed("down")}, default=HITS)
    rig = Rig(db_pool, [suggest_answer("Ideas.", card("Krabi", "TH", [1]))], search)
    events = run(rig, turn_for(db_conn, conversation, "Ideas please"), "suggest", "bad")
    assert events[-1].type == "suggestions"
    assert search.calls[0] == "bad" and len(rig.provider.calls) == 1


def test_answer_turn_makes_no_search(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [reply_answer("December is dry in the south.")], FakeSearch())
    question = "Is December a good month for Thailand?"
    events = run(rig, turn_for(db_conn, conversation, question), "answer")
    assert rig.search.calls == [] and len(rig.provider.calls) == 1
    assert {e.type for e in events} == {"token"}
    assert recent_messages(db_conn, conversation.id, 1)[-1].intent == "answer"


def test_draft_is_saved_before_the_first_token(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [reply_answer("Which month?", {"origin": "Hanoi"})], FakeSearch())
    events = run_discovery_turn(turn_for(db_conn, conversation, "hi"), rig.deps, "ask")
    next(events)
    assert get_conversation(db_conn, conversation.id).request_draft == {"origin": "Hanoi"}
    events.close()


def test_closing_the_stream_after_the_first_token_saves_the_text_so_far(
    db_pool, db_conn, conversation
):
    reply = "Which month do you want to travel, and for how long?"
    rig = Rig(db_pool, [reply_answer(reply, {"travelers": 2})], FakeSearch())
    events = run_discovery_turn(turn_for(db_conn, conversation, "hi"), rig.deps, "ask")
    first = next(events)
    events.close()
    last = recent_messages(db_conn, conversation.id, 1)[-1]
    assert (last.role, last.content, last.intent) == ("assistant", first.data["text"], "ask")
    assert get_conversation(db_conn, conversation.id).request_draft == {"travelers": 2}


def test_suggest_turn_saves_nothing_when_the_model_output_stays_invalid(
    db_pool, db_conn, conversation
):
    rig = Rig(db_pool, ["not json", "still not json"], FakeSearch(default=HITS))
    turn = turn_for(db_conn, conversation, "Ideas please")
    with pytest.raises(InvalidLLMOutput):
        run(rig, turn, "suggest")
    assert [m.role for m in recent_messages(db_conn, conversation.id, 5)] == ["user"]
    assert get_conversation(db_conn, conversation.id).request_draft is None


def test_discovery_queries_use_the_month_origin_and_styles_in_english():
    draft = RequestDraft(month="December", origin="Hanoi", travel_styles=("food", "nature"))
    queries = discovery_queries(draft, "en")
    assert len(queries) == 3
    assert all("December" in q and "Hanoi" in q and "food and nature" in q for q in queries[:1])


def test_discovery_queries_are_vietnamese_for_vi():
    draft = RequestDraft(origin="Hà Nội", travel_styles=("food",))
    assert all("ẩm thực" in q for q in discovery_queries(draft, "vi"))


def test_merge_draft_ignores_empty_values():
    merged = merge_draft({"origin": "Hanoi"}, RequestDraft(travelers=2))
    assert merged == {"origin": "Hanoi", "travelers": 2}
