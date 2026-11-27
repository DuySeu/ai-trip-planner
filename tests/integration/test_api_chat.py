from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from api.routes.chat import get_chat_deps, sse_stream
from core.constants import ModelId
from core.settings import load_settings
from db.pool import open_pool
from db.repositories import conversations, messages, quota, trips, users
from db.repositories.trips import TripRow
from orchestration.state_manager import prepare_message
from service.tavily.search import SearchHit
from tests.fakes import FakeSearch
from tests.fixtures.builders import DALAT_FIELDS, dalat_plan
from tests.integration.test_api_foundation import ENV, make_app
from tests.integration.test_chat_service import ANSWER, NOW, Rig, route
from tests.integration.test_discovery_turn import card, suggest_answer

HITS = [SearchHit("Beach guide", "https://example.com/b", "Krabi is dry in December.")]


# A client on an app whose chat runs against the scripted rig
def chat_client(
    pool: ConnectionPool, script: Sequence[str | Exception], **env: str
) -> tuple[TestClient, Rig]:
    rig = Rig(pool, script, FakeSearch(default=HITS))
    app = make_app(pool, load_settings({**ENV, **env}))
    app.dependency_overrides[get_chat_deps] = lambda: rig.deps
    return TestClient(app, raise_server_exceptions=False), rig


# A named user and one conversation of theirs
@pytest.fixture
def conversation(db_conn):
    user = users.claim_user(db_conn, "Duy")
    return conversations.create_conversation(db_conn, user.id, None)


# A ready Da Lat trip of the user at plan revision 1
def ready_trip(db_conn: Any, user_id: UUID) -> TripRow:
    trip = trips.create_trip(db_conn, user_id, DALAT_FIELDS, None)
    return trips.save_plan(
        db_conn, trip.id, 0, dalat_plan().model_dump(mode="json"), Decimal("1000000"), False, "m"
    )


# Send a message and read the whole reply as (event name, data) pairs
def send(
    client: TestClient, conversation_id: UUID, content: str, **fields: Any
) -> list[tuple[str, dict[str, Any]]]:
    with client.stream(
        "POST",
        "/chat",
        json={"conversation_id": str(conversation_id), "content": content, **fields},
    ) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        return parse_sse(response.read().decode())


# The events of an SSE body
def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_chat_post_streams_sse_events_ending_with_done(db_pool, db_conn, conversation):
    client, _ = chat_client(db_pool, [route("advice"), ANSWER])
    events = send(client, conversation.id, "  Is Da Lat cold in December?  ")

    assert events[-1] == ("done", {})
    assert {name for name, _ in events[:-1]} == {"token"}
    assert "".join(data["text"] for _, data in events if "text" in data) == ANSWER
    saved = messages.recent_messages(db_conn, conversation.id, 5)
    assert [(m.role, m.content, m.intent) for m in saved] == [
        ("user", "Is Da Lat cold in December?", None),
        ("assistant", ANSWER, "advice"),
    ]
    assert conversations.get_conversation(db_conn, conversation.id).title == (
        "Is Da Lat cold in December?"
    )


def test_title_is_the_first_message_cut_to_80_chars_and_is_not_replaced(
    db_pool, db_conn, conversation
):
    client, _ = chat_client(db_pool, [route("advice"), ANSWER, route("advice"), ANSWER])
    send(client, conversation.id, "x" * 200)
    send(client, conversation.id, "second message")
    assert conversations.get_conversation(db_conn, conversation.id).title == "x" * 80


def test_chat_with_stale_plan_revision_returns_409_json_not_stream(db_pool, db_conn, conversation):
    trip = ready_trip(db_conn, conversation.user_id)
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "Move lunch",
            "trip_id": str(trip.id),
            "plan_revision": trip.plan_revision + 1,
        },
    )
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "conflict"
    assert messages.recent_messages(db_conn, conversation.id, 5) == []


def test_chat_over_daily_name_cap_returns_429(db_pool, db_conn, conversation):
    messages.add_message(db_conn, conversation.id, "user", "earlier")
    client, _ = chat_client(db_pool, [], USER_CHAT_PER_DAY="1")
    response = client.post(
        "/chat", json={"conversation_id": str(conversation.id), "content": "more"}
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert len(messages.recent_messages(db_conn, conversation.id, 5)) == 1


def test_chat_while_the_ai_quota_is_blocked_returns_429_quota_exhausted(
    db_pool, db_conn, conversation
):
    quota.block(db_conn, "openrouter", NOW + timedelta(days=30), "daily cap")
    client, _ = chat_client(db_pool, [])
    response = client.post("/chat", json={"conversation_id": str(conversation.id), "content": "hi"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exhausted"
    assert messages.recent_messages(db_conn, conversation.id, 5) == []


QUESTIONNAIRE = {"kind": "questionnaire", "status": "open", "step": 0, "answers": {}, "choices": {}}


def test_discovery_flow_opens_a_card_takes_an_answer_then_suggests(db_pool, db_conn, conversation):
    script = [
        route("discover"),
        json.dumps({}),
        suggest_answer("Here are some ideas.", card("Krabi", "TH", [1])),
    ]
    client, rig = chat_client(db_pool, script)
    events = send(client, conversation.id, "Warm beach, no idea where")
    assert [name for name, _ in events] == ["metadata", "done"]
    card_id = events[0][1]["message_id"]
    assert events[0][1]["metadata"] == QUESTIONNAIRE

    response = client.patch(
        f"/conversations/{conversation.id}/messages/{card_id}",
        json={"step": 2, "choice": "2", "answers": {}},
    )
    assert response.status_code == 200
    meta = response.json()["data"]["metadata"]
    assert (meta["step"], meta["answers"], meta["choices"]) == (2, {"travelers": 2}, {"2": "2"})

    events = send(
        client, conversation.id, "Suggest destinations for me", discover_message_id=card_id
    )
    assert [name for name, _ in events][-2:] == ["metadata", "done"]
    cards = events[-2][1]["metadata"]["cards"]
    assert [c["name"] for c in cards] == ["Krabi"]
    assert len(rig.provider.calls) == 3  # one router call, for the first message only
    last = messages.recent_messages(db_conn, conversation.id, 1)[-1]
    assert (last.intent, last.metadata) == ("discover", {"kind": "suggestions", "cards": cards})


def test_get_conversation_returns_metadata_not_suggestions(db_pool, db_conn, conversation):
    messages.add_message(db_conn, conversation.id, "assistant", "", "discover", QUESTIONNAIRE)
    client, _ = chat_client(db_pool, [])
    [message] = client.get(f"/conversations/{conversation.id}").json()["data"]["messages"]
    assert message["metadata"] == QUESTIONNAIRE
    assert "suggestions" not in message


def test_chat_with_both_follow_up_ids_is_422(db_pool, conversation):
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "Go",
            "discover_message_id": str(uuid4()),
            "booking_message_id": str(uuid4()),
            "dates": {"check_in": "2026-12-20", "check_out": "2026-12-22"},
        },
    )
    assert response.status_code == 422


def test_chat_booking_follow_up_without_dates_is_422(db_pool, conversation):
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "Go",
            "booking_message_id": str(uuid4()),
        },
    )
    assert response.status_code == 422


def test_chat_booking_follow_up_with_past_dates_is_422_json(db_pool, db_conn, conversation):
    meta = {"kind": "hotel", "status": "need_dates", "query": "hotel"}
    card_row = messages.add_message(
        db_conn, conversation.id, "assistant", "When?", "booking_search", meta
    )
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "Search",
            "booking_message_id": str(card_row.id),
            "dates": {"check_in": "2026-01-01", "check_out": "2026-01-03"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "past" in response.json()["error"]["message"]


def test_chat_follow_up_on_another_conversation_is_404(db_pool, db_conn, conversation):
    other = conversations.create_conversation(db_conn, conversation.user_id, None)
    card_row = messages.add_message(db_conn, other.id, "assistant", "", "discover", QUESTIONNAIRE)
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "Suggest",
            "discover_message_id": str(card_row.id),
        },
    )
    assert response.status_code == 404


def test_chat_with_other_users_trip_returns_404(db_pool, db_conn, conversation):
    other = users.claim_user(db_conn, "Linh")
    trip = ready_trip(db_conn, other.id)
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "Show it",
            "trip_id": str(trip.id),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert messages.recent_messages(db_conn, conversation.id, 5) == []


def test_message_over_4000_chars_returns_422(db_pool, db_conn, conversation):
    client, _ = chat_client(db_pool, [])
    cid = str(conversation.id)
    assert (
        client.post("/chat", json={"conversation_id": cid, "content": "x" * 4001}).status_code
        == 422
    )
    assert (
        client.post("/chat", json={"conversation_id": cid, "content": "  \n\t "}).status_code == 422
    )
    assert client.post("/chat", json={"conversation_id": cid}).status_code == 422
    assert client.post("/chat", json={"content": "hi"}).status_code == 422
    assert messages.recent_messages(db_conn, conversation.id, 5) == []


def test_message_to_unknown_conversation_returns_404(db_pool):
    client, _ = chat_client(db_pool, [])
    response = client.post("/chat", json={"conversation_id": str(uuid4()), "content": "hi"})
    assert response.status_code == 404


def test_streaming_does_not_hold_a_pooled_connection(migrated_db, db_conn, conversation):
    # With one connection in the pool, a route that kept its connection would starve the stream
    with open_pool(migrated_db, max_size=1) as pool:
        client, _ = chat_client(pool, [route("advice"), ANSWER])
        events = send(client, conversation.id, "Is Da Lat cold?")
    assert events[-1] == ("done", {})
    assert messages.recent_messages(db_conn, conversation.id, 5)[-1].content == ANSWER


def test_closing_the_stream_early_saves_the_text_sent_so_far(db_pool, db_conn, conversation):
    _, rig = chat_client(db_pool, [route("advice"), ANSWER])
    with db_pool.connection() as conn:
        turn = prepare_message(conn, conversation.id, "Is Da Lat cold?", None, None)

    stream = sse_stream(turn, rig.deps)
    first = next(stream)
    assert first.startswith("event: token\n")
    stream.close()

    last = messages.recent_messages(db_conn, conversation.id, 5)[-1]
    assert last.role == "assistant" and last.intent == "advice"
    assert 0 < len(last.content) < len(ANSWER)
    assert ANSWER.startswith(last.content)


def test_create_conversation_keeps_only_the_filled_draft_fields(db_pool, db_conn):
    client, _ = chat_client(db_pool, [])
    user = users.claim_user(db_conn, "Duy")
    response = client.post(
        "/conversations",
        json={"user_id": str(user.id), "draft": {"origin": "Hanoi", "travelers": 2, "notes": None}},
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["request_draft"] == {"origin": "Hanoi", "travelers": 2}
    assert data["title"] is None

    bad = client.post("/conversations", json={"user_id": str(user.id), "draft": {"travelers": 0}})
    assert bad.status_code == 422
    missing = client.post("/conversations", json={"user_id": str(uuid4())})
    assert missing.status_code == 404


CHOSEN = ModelId.PARTICLE_1


def test_patch_sets_and_resets_chat_model_and_keeps_title(db_pool, db_conn, conversation):
    client, _ = chat_client(db_pool, [])
    conversations.rename_conversation(db_conn, conversation.id, "Sapa")
    url = f"/conversations/{conversation.id}"

    chosen = client.patch(url, json={"chat_model": CHOSEN}).json()["data"]
    assert (chosen["chat_model"], chosen["title"]) == (CHOSEN, "Sapa")
    assert client.get(url).json()["data"]["chat_model"] == CHOSEN

    reset = client.patch(url, json={"chat_model": None}).json()["data"]
    assert (reset["chat_model"], reset["title"]) == (None, "Sapa")


def test_rename_keeps_chat_model(db_pool, db_conn, conversation):
    client, _ = chat_client(db_pool, [])
    conversations.set_chat_model(db_conn, conversation.id, CHOSEN)
    data = client.patch(f"/conversations/{conversation.id}", json={"title": "Hue"}).json()["data"]
    assert (data["title"], data["chat_model"]) == ("Hue", CHOSEN)


def test_patch_with_unknown_model_is_422(db_pool, conversation):
    client, _ = chat_client(db_pool, [])
    response = client.patch(f"/conversations/{conversation.id}", json={"chat_model": "gpt-x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_patch_with_empty_body_is_422(db_pool, conversation):
    client, _ = chat_client(db_pool, [])
    assert client.patch(f"/conversations/{conversation.id}", json={}).status_code == 422


def test_create_conversation_with_chat_model(db_pool, db_conn):
    client, _ = chat_client(db_pool, [])
    user = users.claim_user(db_conn, "Duy")
    body = {"user_id": str(user.id), "draft": None}
    created = client.post("/conversations", json={**body, "chat_model": CHOSEN})
    assert created.status_code == 201
    assert created.json()["data"]["chat_model"] == CHOSEN
    unknown = client.post("/conversations", json={**body, "chat_model": "gpt-x"})
    assert unknown.status_code == 422


def test_list_conversations_newest_first_with_paging(db_pool, db_conn):
    client, _ = chat_client(db_pool, [])
    user = users.claim_user(db_conn, "Duy")
    first = conversations.create_conversation(db_conn, user.id, None)
    second = conversations.create_conversation(db_conn, user.id, None)
    conversations.touch_conversation(db_conn, first.id)

    body = client.get(f"/users/{user.id}/conversations").json()
    assert [c["id"] for c in body["data"]] == [str(first.id), str(second.id)]
    assert body["meta"] == {"total": 2, "limit": 20, "offset": 0}
    page = client.get(f"/users/{user.id}/conversations", params={"limit": 1, "offset": 1}).json()
    assert [c["id"] for c in page["data"]] == [str(second.id)]
    assert client.get(f"/users/{uuid4()}/conversations").status_code == 404


def test_get_conversation_returns_messages_in_order_and_pages_them(db_pool, db_conn, conversation):
    messages.add_message(db_conn, conversation.id, "user", "one")
    messages.add_message(db_conn, conversation.id, "assistant", "two", "advice")
    messages.add_message(db_conn, conversation.id, "user", "three")
    client, _ = chat_client(db_pool, [])

    body = client.get(f"/conversations/{conversation.id}").json()
    assert [m["content"] for m in body["data"]["messages"]] == ["one", "two", "three"]
    assert body["meta"]["total"] == 3
    page = client.get(f"/conversations/{conversation.id}", params={"limit": 2, "offset": 2}).json()
    assert [m["content"] for m in page["data"]["messages"]] == ["three"]
    assert client.get(f"/conversations/{uuid4()}").status_code == 404


def test_rename_conversation_keeps_updated_at(db_pool, db_conn, conversation):
    client, _ = chat_client(db_pool, [])
    url = f"/conversations/{conversation.id}"
    response = client.patch(url, json={"title": "  Beach ideas  "})
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "Beach ideas"
    stored = conversations.get_conversation(db_conn, conversation.id)
    assert stored.title == "Beach ideas" and stored.updated_at == conversation.updated_at

    assert client.patch(url, json={"title": "   "}).status_code == 422
    assert client.patch(url, json={"title": "x" * 81}).status_code == 422
    assert client.patch(f"/conversations/{uuid4()}", json={"title": "a"}).status_code == 404


def test_delete_conversation_removes_its_messages(db_pool, db_conn, conversation):
    messages.add_message(db_conn, conversation.id, "user", "hello")
    trips.create_trip(db_conn, conversation.user_id, DALAT_FIELDS, None)
    client, _ = chat_client(db_pool, [])

    response = client.delete(f"/conversations/{conversation.id}")
    assert response.status_code == 204 and response.content == b""
    assert client.get(f"/conversations/{conversation.id}").status_code == 404
    assert db_conn.execute("SELECT count(*) FROM messages").fetchone() == (0,)
    assert client.delete(f"/conversations/{conversation.id}").status_code == 404


FORM = {"status": "open", "draft": {"length_days": 3}, "trip_id": None}


def form_message(db_conn: Any, conversation_id: UUID, metadata: dict[str, Any] = FORM) -> Any:
    return messages.add_message(db_conn, conversation_id, "assistant", "", "create_trip", metadata)


def test_patch_cancels_an_open_form(db_pool, db_conn, conversation):
    form = form_message(db_conn, conversation.id)
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{form.id}", json={"status": "canceled"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["id"], data["intent"]) == (str(form.id), "create_trip")
    assert data["metadata"] == {**FORM, "status": "canceled"}
    assert messages.get_message(db_conn, form.id).metadata == {**FORM, "status": "canceled"}


def test_patch_cancel_on_a_created_form_conflicts(db_pool, db_conn, conversation):
    created = {**FORM, "status": "created", "trip_id": str(uuid4())}
    form = form_message(db_conn, conversation.id, created)
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{form.id}", json={"status": "canceled"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert messages.get_message(db_conn, form.id).metadata == created


def test_cancel_message_of_other_conversation_returns_404(db_pool, db_conn, conversation):
    other = conversations.create_conversation(db_conn, conversation.user_id, None)
    form = form_message(db_conn, other.id)
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{form.id}", json={"status": "canceled"}
    )
    assert response.status_code == 404
    assert messages.get_message(db_conn, form.id).metadata == FORM


def test_patch_with_an_unknown_body_is_422(db_pool, db_conn, conversation):
    form = form_message(db_conn, conversation.id)
    client, _ = chat_client(db_pool, [])
    for body in ({"status": "created"}, {"intent": "canceled_trip"}, {"step": 7}):
        response = client.patch(f"/conversations/{conversation.id}/messages/{form.id}", json=body)
        assert response.status_code == 422
    assert messages.get_message(db_conn, form.id).metadata == FORM


def test_patch_answers_a_questionnaire_step(db_pool, db_conn, conversation):
    card_row = messages.add_message(
        db_conn, conversation.id, "assistant", "", "discover", QUESTIONNAIRE
    )
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{card_row.id}", json={"step": 2, "choice": "2"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["metadata"]["choices"] == {"2": "2"}
    assert conversations.get_conversation(db_conn, conversation.id).request_draft == {
        "travelers": 2
    }


def test_patch_with_an_unknown_choice_is_422(db_pool, db_conn, conversation):
    card_row = messages.add_message(
        db_conn, conversation.id, "assistant", "", "discover", QUESTIONNAIRE
    )
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{card_row.id}",
        json={"step": 4, "choice": "paris"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert messages.get_message(db_conn, card_row.id).metadata == QUESTIONNAIRE


def test_patch_answer_on_a_form_message_conflicts(db_pool, db_conn, conversation):
    form = form_message(db_conn, conversation.id)
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{form.id}", json={"step": 2, "choice": "2"}
    )
    assert response.status_code == 409


def test_patch_cancel_on_a_questionnaire_conflicts(db_pool, db_conn, conversation):
    card_row = messages.add_message(
        db_conn, conversation.id, "assistant", "", "discover", QUESTIONNAIRE
    )
    client, _ = chat_client(db_pool, [])
    response = client.patch(
        f"/conversations/{conversation.id}/messages/{card_row.id}", json={"status": "canceled"}
    )
    assert response.status_code == 409


@pytest.mark.parametrize("default_origin", ["", "   ", "x" * 201])
def test_chat_body_rejects_blank_or_too_long_default_origin(
    db_pool, db_conn, conversation, default_origin
):
    client, _ = chat_client(db_pool, [])
    response = client.post(
        "/chat",
        json={
            "conversation_id": str(conversation.id),
            "content": "hi",
            "default_origin": default_origin,
        },
    )
    assert response.status_code == 422
    assert messages.recent_messages(db_conn, conversation.id, 5) == []
