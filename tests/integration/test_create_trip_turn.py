from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from chat.chat_service import ChatDeps, prepare_message, stream_reply
from chat.events import ChatEvent
from core.constants import ModelId
from core.exceptions import QuotaExhausted, ResearchFailed
from core.settings import load_settings
from db.repositories.conversations import create_conversation, get_conversation, save_draft
from db.repositories.messages import recent_messages
from db.repositories.users import claim_user
from domain.trip_request import Language
from models.model_router import ModelRouter
from research.places import Place
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
PURPOSES = ("classify", "repair", "discover")
HAI_PHONG = Place("Hải Phòng", "Hải Phòng", "VN", 20.86, 106.68)
EXTRACT = json.dumps({"destination_name": "Hải Phòng", "length_days": 3, "origin": "Hà Nội"})


# The classifier's JSON for a message routed to create_trip
def route_to_create_trip() -> str:
    step = {"id": "s1", "agent": "create_trip", "task": "plan"}
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


# The deps, the provider script and the places double of one test
class Rig:
    def __init__(
        self,
        pool: ConnectionPool,
        script: Sequence[str | Exception],
        found: Sequence[Place] | Exception = (HAI_PHONG,),
    ) -> None:
        self.provider = FakeProvider([route_to_create_trip(), *script])
        self.places_calls: list[tuple[str, Language]] = []
        self.pool = pool

        def places(query: str, language: Language) -> list[Place]:
            self.places_calls.append((query, language))
            if isinstance(found, Exception):
                raise found
            return list(found)

        router = ModelRouter(
            llm=self.provider,
            models={purpose: [MODEL] for purpose in PURPOSES},  # type: ignore[misc]
            sink=FakeSink(),
            reset_hour_utc=0,
            now=lambda: NOW,
        )
        self.deps = ChatDeps(pool, router, FakeSearch(), load_settings(ENV), lambda: NOW, places)

    # Save the visitor's message and stream the reply to the end
    def say(self, conversation_id: Any, content: str) -> list[ChatEvent]:
        with self.pool.connection() as conn:
            turn = prepare_message(conn, conversation_id, content, None, None)
        return list(stream_reply(turn, self.deps))


@pytest.fixture
def conversation(db_conn):
    return create_conversation(db_conn, claim_user(db_conn, "Duy").id, None)


def test_create_trip_turn_saves_form_metadata_and_emits_metadata_event(
    db_pool, db_conn, conversation
):
    rig = Rig(db_pool, [EXTRACT])
    events = rig.say(conversation.id, "tạo plan trip cho tôi")

    expected = {
        "destination": {"name": "Hải Phòng", "country_code": "VN", "lat": 20.86, "lon": 106.68},
        "origin": "Hà Nội",
        "length_days": 3,
    }
    assert [e.type for e in events] == ["metadata", "done"]
    form = {"status": "open", "draft": expected, "trip_id": None}
    assert events[0].data["metadata"] == form
    last = recent_messages(db_conn, conversation.id, 2)[-1]
    assert (last.role, last.intent, last.content) == ("assistant", "create_trip", "")
    assert last.metadata == form
    assert events[0].data["message_id"] == str(last.id)
    assert get_conversation(db_conn, conversation.id).request_draft == expected
    assert len(rig.provider.calls) == 2


def test_unknown_destination_leaves_destination_out(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [EXTRACT], found=[])
    events = rig.say(conversation.id, "plan a trip")
    assert events[0].type == "metadata"
    assert events[0].data["metadata"]["draft"] == {"origin": "Hà Nội", "length_days": 3}


def test_geocoder_failure_leaves_destination_out(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [EXTRACT], found=ResearchFailed("geocoder down"))
    events = rig.say(conversation.id, "plan a trip")
    assert events[0].type == "metadata"
    assert "destination" not in events[0].data["metadata"]["draft"]


def test_invalid_model_output_still_gives_form_from_old_draft(db_pool, db_conn, conversation):
    save_draft(db_conn, conversation.id, {"travelers": 4})
    rig = Rig(db_pool, ["not json", "still not json"])
    events = rig.say(conversation.id, "plan a trip")
    assert [e.type for e in events] == ["metadata", "done"]
    assert events[0].data["metadata"]["draft"] == {"travelers": 4}
    assert rig.places_calls == []


def test_quota_exhausted_sends_error_and_saves_no_message(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [QuotaExhausted(NOW)])
    events = rig.say(conversation.id, "plan a trip")
    assert [e.type for e in events] == ["error", "done"]
    assert events[0].data["code"] == "quota_exhausted"
    assert [m.role for m in recent_messages(db_conn, conversation.id, 5)] == ["user"]


def test_vietnamese_message_searches_places_in_vietnamese(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [EXTRACT])
    rig.say(conversation.id, "tạo plan trip cho tôi")
    assert rig.places_calls == [("Hải Phòng", "vi")]


def test_english_message_searches_places_in_english(db_pool, db_conn, conversation):
    rig = Rig(db_pool, [EXTRACT])
    rig.say(conversation.id, "plan a trip for me")
    assert rig.places_calls == [("Hải Phòng", "en")]


def test_past_dates_from_the_model_are_not_kept(db_pool, db_conn, conversation):
    answer = json.dumps({"start_date": "2026-11-01", "end_date": "2026-11-03", "length_days": 3})
    rig = Rig(db_pool, [answer])
    events = rig.say(conversation.id, "plan a 3 day trip")
    assert events[0].data["metadata"]["draft"] == {"length_days": 3}
