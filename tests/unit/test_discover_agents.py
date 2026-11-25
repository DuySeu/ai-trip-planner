from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from agents.create_trip_agent import CreateTripAgent, drop_past_dates
from agents.discover_suggest_agent import DiscoverSuggestAgent
from core.constants import ModelId
from domain.discovery import (
    MAX_CARDS,
    SuggestionsReply,
    TripFormExtract,
)
from models.model_router import CallContext, ModelRouter
from tests.fakes import FakeProvider, FakeSink

MODEL = ModelId.LING_3_2_FLASH
TODAY = date(2026, 11, 17)
DRAFT = {"origin": "Hanoi", "travelers": 2}
CONVERSATION = "<conversation>\nuser: hi\nassistant: hello\n</conversation>"
SOURCES = '<source id="1" kind="chat" title="Krabi" url="https://example.com/krabi">Dry.</source>'
CTX = CallContext()


# A router whose only model answers from the provider; the sink records every call
def make_router(provider: FakeProvider) -> tuple[ModelRouter, FakeSink]:
    sink = FakeSink()
    router = ModelRouter(
        llm=provider,
        models={"discover": [MODEL], "suggest": [MODEL], "repair": [MODEL]},
        sink=sink,
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 17, 15, 0, tzinfo=UTC),
    )
    return router, sink


def card(name: str, country: str, source_ids: Sequence[int] = ()) -> dict[str, Any]:
    return {
        "name": name,
        "country_code": country,
        "why": "Dry and quiet in December.",
        "length_days": 4,
        "est_cost_per_person_vnd": "9000000",
        "source_ids": list(source_ids),
    }


def suggest_answer(*cards: dict[str, Any]) -> str:
    return json.dumps({"reply": "Try these.", "request_draft": {}, "cards": list(cards)})


def suggest(provider: FakeProvider, known: frozenset[int] = frozenset({1})) -> SuggestionsReply:
    router, _ = make_router(provider)
    return DiscoverSuggestAgent(router).run(
        DRAFT, TODAY, CONVERSATION, SOURCES, known, "where to go?", CTX
    )


def user_content(provider: FakeProvider, call: int = 0) -> str:
    return provider.calls[call][0][0]["content"]


def test_create_trip_prompt_holds_today_draft_conversation_and_request_in_order():
    provider = FakeProvider(["{}"])
    router, _ = make_router(provider)
    CreateTripAgent(router).run(DRAFT, TODAY, CONVERSATION, "somewhere warm", CTX)
    content = user_content(provider)
    assert "<today>2026-11-17</today>" in content
    assert f"<draft>\n{json.dumps(DRAFT)}\n</draft>" in content
    assert CONVERSATION in content
    assert "<request>\nsomewhere warm\n</request>" in content
    assert "<sources>" not in content
    assert content.index("<draft>") < content.index("<conversation>") < content.index("<request>")


def test_create_trip_prompt_leaves_out_an_empty_conversation():
    provider = FakeProvider(["{}"])
    router, _ = make_router(provider)
    CreateTripAgent(router).run(DRAFT, TODAY, "", "somewhere warm", CTX)
    assert "<conversation>" not in user_content(provider)


def test_suggest_agent_makes_one_suggest_call_and_returns_the_cards():
    provider = FakeProvider([suggest_answer(card("Krabi", "TH", [1]))])
    router, sink = make_router(provider)
    result = DiscoverSuggestAgent(router).run(
        DRAFT, TODAY, CONVERSATION, SOURCES, frozenset({1}), "where to go?", CTX
    )
    assert [(c.name, c.source_ids) for c in result.cards] == [("Krabi", (1,))]
    assert len(provider.calls) == 1
    assert [r.purpose for r in sink.logs] == ["suggest"]


def test_suggest_prompt_holds_the_sources_block_and_the_draft_json():
    provider = FakeProvider([suggest_answer(card("Krabi", "TH"))])
    suggest(provider)
    content = user_content(provider)
    assert f"<sources>\n{SOURCES}\n</sources>" in content
    assert f"<draft>\n{json.dumps(DRAFT)}\n</draft>" in content
    assert CONVERSATION in content
    assert content.index("<draft>") < content.index("<sources>") < content.index("<conversation>")
    assert content.endswith("<request>\nwhere to go?\n</request>")


def test_suggest_prompt_says_none_when_there_are_no_sources():
    provider = FakeProvider([suggest_answer(card("Krabi", "TH"))])
    router, _ = make_router(provider)
    DiscoverSuggestAgent(router).run(DRAFT, TODAY, "", "", frozenset(), "where to go?", CTX)
    content = user_content(provider)
    assert "<sources>\nnone\n</sources>" in content
    assert "<conversation>" not in content


def test_suggest_agent_drops_a_card_with_an_unsupported_country():
    provider = FakeProvider([suggest_answer(card("Atlantis", "ZZ"), card("Krabi", "TH"))])
    result = suggest(provider)
    assert [c.name for c in result.cards] == ["Krabi"]
    assert len(provider.calls) == 1


def test_suggest_agent_strips_source_ids_the_research_does_not_hold():
    provider = FakeProvider([suggest_answer(card("Krabi", "TH", [1, 99]))])
    assert suggest(provider).cards[0].source_ids == (1,)


def test_suggest_agent_cuts_the_cards_to_the_maximum():
    cards = [card(f"Place {n}", "TH") for n in range(MAX_CARDS + 2)]
    provider = FakeProvider([suggest_answer(*cards)])
    assert len(suggest(provider).cards) == MAX_CARDS


def test_suggest_agent_repairs_once_when_no_usable_card_is_left():
    provider = FakeProvider(
        [suggest_answer(card("Atlantis", "ZZ")), suggest_answer(card("Krabi", "TH"))]
    )
    router, sink = make_router(provider)
    result = DiscoverSuggestAgent(router).run(
        DRAFT, TODAY, CONVERSATION, SOURCES, frozenset({1}), "where to go?", CTX
    )
    assert [c.name for c in result.cards] == ["Krabi"]
    assert len(provider.calls) == 2
    assert [r.purpose for r in sink.logs] == ["suggest", "repair"]
    assert "country_code" in provider.calls[1][0][2]["content"]


def test_create_trip_agent_makes_one_discover_call_and_returns_the_extract():
    answer = json.dumps({"destination_name": "Hải Phòng", "length_days": 3, "origin": "Hà Nội"})
    provider = FakeProvider([answer])
    router, sink = make_router(provider)
    result = CreateTripAgent(router).run(DRAFT, TODAY, CONVERSATION, "tạo plan trip", CTX)
    assert result == TripFormExtract(destination_name="Hải Phòng", length_days=3, origin="Hà Nội")
    assert len(provider.calls) == 1
    assert [r.purpose for r in sink.logs] == ["discover"]
    content = user_content(provider)
    assert "<today>2026-11-17</today>" in content
    assert CONVERSATION in content
    assert "<request>\ntạo plan trip\n</request>" in content


def test_create_trip_prompt_hides_destination_and_shows_destination_name():
    provider = FakeProvider(["{}"])
    router, _ = make_router(provider)
    CreateTripAgent(router).run(DRAFT, TODAY, CONVERSATION, "plan a trip", CTX)
    system = provider.calls[0][1]
    assert '"destination_name"' in system
    assert '"destination"' not in system
    assert '"length_days"' in system


def test_drop_past_dates_removes_dates_before_today():
    extract = TripFormExtract(
        start_date=date(2026, 11, 16), end_date=date(2026, 11, 18), length_days=3
    )
    result = drop_past_dates(extract, TODAY)
    assert (result.start_date, result.end_date, result.length_days) == (None, None, 3)


def test_drop_past_dates_keeps_future_dates():
    extract = TripFormExtract(start_date=TODAY, end_date=date(2026, 11, 19))
    assert drop_past_dates(extract, TODAY) == extract
