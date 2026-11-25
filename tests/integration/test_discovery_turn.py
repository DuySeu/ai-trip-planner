from __future__ import annotations

import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from chat.chat_service import ChatDeps, ChatTurn, FollowUp, prepare_message, stream_reply
from chat.discovery_turn import (
    MAX_QUERIES,
    discovery_queries,
    run_discover_turn,
    run_suggest_turn,
)
from chat.events import ChatEvent
from chat.questionnaire_service import answer_questionnaire
from core.constants import ModelId
from core.exceptions import Conflict, InvalidInput, InvalidLLMOutput, NotFound, ResearchFailed
from core.settings import load_settings
from db.repositories.conversations import create_conversation, get_conversation, save_draft
from db.repositories.messages import add_message, get_message, list_messages, recent_messages
from db.repositories.users import claim_user
from domain.discovery import RequestDraft, merge_draft
from models.model_router import CallContext, ModelRouter
from service.tavily.search import SearchHit
from tests.fakes import FakeProvider, FakeSearch, FakeSink

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
HITS = [
    SearchHit("Krabi in December", "https://example.com/krabi", "Krabi is dry in December."),
    SearchHit("Da Nang beaches", "https://example.com/danang", "Da Nang is cool in December."),
]


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
            llm=self.provider,
            models={p: [MODEL] for p in ("classify", "discover", "suggest", "repair")},  # type: ignore[misc]
            sink=FakeSink(),
            reset_hour_utc=0,
            now=lambda: NOW,
        )
        self.deps = ChatDeps(
            pool, router, search, load_settings(ENV), lambda: NOW, lambda q, language: []
        )


TODAY = date(2026, 11, 17)
CARD = {"kind": "questionnaire", "status": "open", "step": 0, "answers": {}, "choices": {}}
FULL_DRAFT = {
    "travel_styles": ["food"],
    "travelers": 2,
    "budget_amount": "6000000",
    "budget_scope": "per_person",
    "origin": "Hanoi",
    "month": "December",
    "length_days": 5,
}
NOTHING = json.dumps({})


@pytest.fixture
def conversation(db_conn):
    return create_conversation(db_conn, claim_user(db_conn, "Duy").id, None)


# Save the visitor's message and return the turn the discovery service runs
def turn_for(db_conn, conversation, content: str, follow_up: FollowUp | None = None) -> ChatTurn:
    message = add_message(db_conn, conversation.id, "user", content)
    return ChatTurn(conversation.id, conversation.user_id, message, None, None, follow_up)


def ctx(turn: ChatTurn) -> CallContext:
    return CallContext(conversation_id=turn.conversation_id, message_id=turn.message.id)


# Run the turn the router starts with discover
def discover(rig: Rig, turn: ChatTurn) -> list[ChatEvent]:
    return list(run_discover_turn(turn, rig.deps, ctx(turn)))


# Open a card, then run the turn the card's suggest button starts
def suggest(rig: Rig, db_conn, conversation, content: str = "Ideas please") -> list[ChatEvent]:
    card = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    turn = turn_for(db_conn, conversation, content, FollowUp(card.id, "discover"))
    return list(run_suggest_turn(turn, rig.deps, ctx(turn)))


def assistant_messages(db_conn, conversation) -> list[Any]:
    return [m for m in list_messages(db_conn, conversation.id, 50, 0) if m.role == "assistant"]


def test_discover_opens_a_card_at_the_first_missing_step(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [json.dumps({"travelers": 2})], FakeSearch())
    events = discover(rig, turn_for(db_conn, conversation, "Hai người muốn đi biển"))

    assert [e.type for e in events] == ["metadata"]
    card = recent_messages(db_conn, conversation.id, 1)[-1]
    assert (card.intent, card.content) == ("discover", "")
    assert card.metadata == {**CARD, "answers": {"travelers": 2}}
    assert events[0].data == {"message_id": str(card.id), "metadata": card.metadata}
    assert rig.search.calls == [] and len(rig.provider.calls) == 1
    assert get_conversation(db_conn, conversation.id).request_draft == {"travelers": 2}


def test_discover_with_a_full_draft_suggests_without_a_card(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, FULL_DRAFT)
    script = [NOTHING, suggest_answer("Ideas.", card("Krabi", "TH", [1]))]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    events = discover(rig, turn_for(db_conn, conversation, "Gợi ý chỗ đi"))

    assert [e.type for e in events][-1] == "metadata"
    assert events[-1].data["message_id"] is None
    assert rig.search.calls != []
    [reply] = assistant_messages(db_conn, conversation)
    assert reply.metadata is not None and reply.metadata["kind"] == "suggestions"


def test_discover_with_an_open_card_closes_it_and_suggests(db_pool, db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    script = [NOTHING, suggest_answer("Ideas.", card("Krabi", "TH", [1]))]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    discover(rig, turn_for(db_conn, conversation, "gợi ý luôn đi"))

    assert get_message(db_conn, card_row.id).metadata == {**CARD, "status": "done"}
    kinds = [(m.metadata or {}).get("kind") for m in assistant_messages(db_conn, conversation)]
    assert kinds == ["questionnaire", "suggestions"]


def test_discover_after_a_done_card_opens_a_new_card(db_pool, db_conn, conversation):
    add_message(db_conn, conversation.id, "assistant", "", "discover", {**CARD, "status": "done"})
    rig = Rig(db_pool, [NOTHING], FakeSearch())
    events = discover(rig, turn_for(db_conn, conversation, "cho tôi ý tưởng khác"))
    assert [e.type for e in events] == ["metadata"]
    assert events[0].data["metadata"]["status"] == "open"


def test_discover_survives_a_failing_extract(db_pool, db_conn, conversation):
    rig = Rig(db_pool, ["not json", "still not json"], FakeSearch())
    events = discover(rig, turn_for(db_conn, conversation, "Somewhere warm"))
    assert [e.type for e in events] == ["metadata"]
    assert events[0].data["metadata"]["status"] == "open"


def test_answer_questionnaire_saves_choice_answer_and_draft(db_conn, conversation):
    save_draft(db_conn, conversation.id, {"travel_styles": ["food"]})
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    saved = answer_questionnaire(db_conn, conversation.id, card_row.id, 3, "saver", {}, TODAY)

    assert saved.metadata is not None
    assert saved.metadata["step"] == 3
    assert saved.metadata["answers"] == {
        "budget_amount": "3000000",
        "budget_scope": "per_person",
        "travel_styles": ["food", "budget"],
    }
    assert saved.metadata["choices"] == {"3": "saver"}
    draft = get_conversation(db_conn, conversation.id).request_draft
    assert draft is not None and draft["budget_amount"] == "3000000"
    assert draft["travel_styles"] == ["food", "budget"]


def test_answering_the_budget_again_swaps_its_style(db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    answer_questionnaire(db_conn, conversation.id, card_row.id, 1, ["food"], {}, TODAY)
    answer_questionnaire(db_conn, conversation.id, card_row.id, 3, "premium", {}, TODAY)
    answer_questionnaire(db_conn, conversation.id, card_row.id, 3, "moderate", {}, TODAY)
    draft = get_conversation(db_conn, conversation.id).request_draft
    assert draft is not None and draft["travel_styles"] == ["food"]


def test_typed_answer_is_saved_with_a_null_choice(db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    saved = answer_questionnaire(
        db_conn, conversation.id, card_row.id, 2, None, {"travelers": 7}, TODAY
    )
    assert saved.metadata is not None
    assert (saved.metadata["answers"], saved.metadata["choices"]) == ({"travelers": 7}, {"2": None})


def test_answer_questionnaire_never_moves_step_back(db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    answer_questionnaire(db_conn, conversation.id, card_row.id, 4, "hanoi", {}, TODAY)
    saved = answer_questionnaire(db_conn, conversation.id, card_row.id, 2, "2", {}, TODAY)
    assert saved.metadata is not None and saved.metadata["step"] == 4


def test_answer_questionnaire_rejects_an_unknown_button(db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    with pytest.raises(InvalidInput):
        answer_questionnaire(db_conn, conversation.id, card_row.id, 4, "paris", {}, TODAY)


def test_answer_questionnaire_on_a_done_card_conflicts(db_conn, conversation):
    done = {**CARD, "status": "done"}
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", done)
    with pytest.raises(Conflict):
        answer_questionnaire(db_conn, conversation.id, card_row.id, 2, "2", {}, TODAY)


def test_answer_questionnaire_of_another_conversation_is_not_found(db_conn, conversation):
    other = create_conversation(db_conn, conversation.user_id, None)
    card_row = add_message(db_conn, other.id, "assistant", "", "discover", CARD)
    with pytest.raises(NotFound):
        answer_questionnaire(db_conn, conversation.id, card_row.id, 2, "2", {}, TODAY)


def test_suggest_follow_up_skips_the_router_closes_the_card_and_saves_suggestions(
    db_pool, db_conn, conversation
):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    script = [suggest_answer("Ideas.", card("Krabi", "TH", [1]))]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    with db_pool.connection() as conn:
        turn = prepare_message(
            conn,
            conversation.id,
            "Suggest destinations for me",
            None,
            None,
            follow_up=FollowUp(card_row.id, "discover"),
        )
    events = list(stream_reply(turn, rig.deps))

    assert len(rig.provider.calls) == 1
    assert [e.type for e in events][-2:] == ["metadata", "done"]
    assert get_message(db_conn, card_row.id).metadata == {**CARD, "status": "done"}
    last = recent_messages(db_conn, conversation.id, 1)[-1]
    assert last.intent == "discover"
    assert last.metadata == {"kind": "suggestions", "cards": events[-2].data["metadata"]["cards"]}


def test_second_suggest_on_the_same_card_conflicts(db_pool, db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    rig = Rig(
        db_pool, [suggest_answer("Ideas.", card("Krabi", "TH", [1]))], FakeSearch(default=HITS)
    )
    follow_up = FollowUp(card_row.id, "discover")
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "Suggest", None, None, follow_up=follow_up)
    list(stream_reply(turn, rig.deps))
    with db_pool.connection() as conn, pytest.raises(Conflict):
        prepare_message(conn, conversation.id, "Suggest", None, None, follow_up=follow_up)


def test_suggest_reopens_the_card_when_the_model_output_stays_invalid(
    db_pool, db_conn, conversation
):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    rig = Rig(db_pool, ["not json", "still not json"], FakeSearch(default=HITS))
    with db_pool.connection() as conn:
        turn = prepare_message(
            conn,
            conversation.id,
            "Suggest",
            None,
            None,
            follow_up=FollowUp(card_row.id, "discover"),
        )
    events = list(stream_reply(turn, rig.deps))
    assert [e.type for e in events] == ["error", "done"]
    assert get_message(db_conn, card_row.id).metadata == CARD


def test_two_answers_at_once_on_one_card_both_stay(db_pool, db_conn, conversation):
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    with db_pool.connection() as first, db_pool.connection() as second:
        answer_questionnaire(first, conversation.id, card_row.id, 2, "2", {}, TODAY)
        # The second answer starts while the first is not committed yet
        with ThreadPoolExecutor(1) as pool:
            late = pool.submit(
                answer_questionnaire, second, conversation.id, card_row.id, 3, "saver", {}, TODAY
            )
            time.sleep(0.2)
            first.commit()
            late.result(timeout=5)
        second.commit()
    meta = get_message(db_conn, card_row.id).metadata
    assert meta is not None and set(meta["choices"]) == {"2", "3"}
    draft = get_conversation(db_conn, conversation.id).request_draft
    assert draft is not None and draft["travelers"] == 2 and "budget_amount" in draft


def test_suggest_on_a_card_of_another_conversation_is_not_found(db_pool, db_conn, conversation):
    other = create_conversation(db_conn, conversation.user_id, None)
    card_row = add_message(db_conn, other.id, "assistant", "", "discover", CARD)
    with db_pool.connection() as conn, pytest.raises(NotFound):
        prepare_message(
            conn,
            conversation.id,
            "Suggest",
            None,
            None,
            follow_up=FollowUp(card_row.id, "discover"),
        )


def test_suggest_with_almost_empty_draft_still_suggests(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {"travel_styles": ["nature"]})
    rig = Rig(
        db_pool, [suggest_answer("Ideas.", card("Sapa", "VN", [1]))], FakeSearch(default=HITS)
    )
    events = suggest(rig, db_conn, conversation)
    assert [c["name"] for c in events[-1].data["metadata"]["cards"]] == ["Sapa"]


def test_suggest_turn_searches_then_streams_cards(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {"origin": "Hanoi"})
    script = [
        suggest_answer(
            "I assume two travelers.",
            card("Krabi", "TH", [1, 99]),
            card("Da Nang", "VN", [2]),
            draft={"month": "December"},
        )
    ]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    events = suggest(rig, db_conn, conversation, "Warm beach in December")

    assert events[-1].type == "metadata" and events[-2].type == "token"
    cards = events[-1].data["metadata"]["cards"]
    assert [(c["name"], c["source_ids"]) for c in cards] == [("Krabi", [1]), ("Da Nang", [2])]
    assert cards[0]["est_cost_per_person_vnd"] == "9000000"
    rows = db_conn.execute(
        "SELECT id, kind, trip_id, conversation_id, title FROM research_results ORDER BY id"
    ).fetchall()
    assert rows == [
        (1, "chat", None, conversation.id, "Krabi in December"),
        (2, "chat", None, conversation.id, "Da Nang beaches"),
    ]
    # The one call saw the saved sources by their ids
    assert 'id="1"' in rig.provider.calls[0][0][0]["content"]
    last = recent_messages(db_conn, conversation.id, 1)[-1]
    assert (last.intent, last.content) == ("discover", "I assume two travelers.")
    assert last.metadata == {"kind": "suggestions", "cards": cards}
    assert get_conversation(db_conn, conversation.id).request_draft == {
        "origin": "Hanoi",
        "month": "December",
    }


def test_suggest_turn_searches_the_draft_queries_then_makes_one_ai_call(
    db_pool, db_conn, conversation
):
    save_draft(db_conn, conversation.id, {"origin": "Hanoi", "travel_styles": ["food"]})
    rig = Rig(
        db_pool, [suggest_answer("Ideas.", card("Krabi", "TH", [1]))], FakeSearch(default=HITS)
    )
    suggest(rig, db_conn, conversation)
    draft = RequestDraft(origin="Hanoi", travel_styles=("food",))
    assert rig.search.calls == list(discovery_queries(draft, "en"))[:MAX_QUERIES]
    assert set(rig.search.tasks) == {"discovery"}
    assert len(rig.provider.calls) == 1


def test_card_with_unknown_country_is_dropped(db_pool, db_conn, conversation):
    script = [suggest_answer("Ideas.", card("Atlantis", "ZZ"), card("Krabi", "TH", [1]))]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    events = suggest(rig, db_conn, conversation)
    assert [c["name"] for c in events[-1].data["metadata"]["cards"]] == ["Krabi"]
    assert len(rig.provider.calls) == 1


def test_cards_without_any_supported_country_get_one_repair_round(db_pool, db_conn, conversation):
    script = [
        suggest_answer("Ideas.", card("Atlantis", "ZZ")),
        suggest_answer("Ideas.", card("Krabi", "TH")),
    ]
    rig = Rig(db_pool, script, FakeSearch(default=HITS))
    events = suggest(rig, db_conn, conversation)
    assert [c["name"] for c in events[-1].data["metadata"]["cards"]] == ["Krabi"]
    assert "country_code" in rig.provider.calls[1][0][-1]["content"]


def test_a_failed_search_is_skipped_and_the_turn_goes_on(db_pool, db_conn, conversation):
    first = discovery_queries(RequestDraft(), "en")[0]
    search = FakeSearch({first: ResearchFailed("down")}, default=HITS)
    rig = Rig(db_pool, [suggest_answer("Ideas.", card("Krabi", "TH", [1]))], search)
    events = suggest(rig, db_conn, conversation)
    assert events[-1].type == "metadata"
    assert search.calls[0] == first and len(rig.provider.calls) == 1


def test_closing_the_stream_after_the_first_token_saves_the_text_so_far(
    db_pool, db_conn, conversation
):
    reply = "I assume two travelers and a week in December."
    rig = Rig(db_pool, [suggest_answer(reply, card("Krabi", "TH", [1]))], FakeSearch(default=HITS))
    card_row = add_message(db_conn, conversation.id, "assistant", "", "discover", CARD)
    turn = turn_for(db_conn, conversation, "Ideas", FollowUp(card_row.id, "discover"))
    events = run_suggest_turn(turn, rig.deps, ctx(turn))
    first = next(events)
    events.close()
    last = recent_messages(db_conn, conversation.id, 1)[-1]
    assert (last.content, last.intent) == (first.data["text"], "discover")
    assert last.metadata == {"kind": "suggestions", "cards": []}


def test_suggest_turn_saves_nothing_when_the_model_output_stays_invalid(
    db_pool, db_conn, conversation
):
    rig = Rig(db_pool, ["not json", "still not json"], FakeSearch(default=HITS))
    with pytest.raises(InvalidLLMOutput):
        suggest(rig, db_conn, conversation)
    assert [m.role for m in recent_messages(db_conn, conversation.id, 5)] == ["assistant", "user"]
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
