from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from chat.history import TRIP_FORM_INTENTS, message_for_model
from db.repositories.messages import MessageRow

HAI_PHONG = {"name": "Hải Phòng", "country_code": "VN", "lat": 20.86, "lon": 106.68}


def row(intent: str | None = None, content: str = "hi") -> MessageRow:
    return MessageRow(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content=content,
        intent=intent,
        suggestions=None,
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
    )


def test_plain_message_is_its_content():
    assert message_for_model(row("travel_advice", "Pack light.")) == "Pack light."
    assert message_for_model(row(None, "hello")) == "hello"


def test_open_form_names_place_and_length():
    content = json.dumps({"destination": HAI_PHONG, "length_days": 3})
    assert message_for_model(row("trip_form", content)) == "[trip form: Hải Phòng, 3 days, open]"


def test_created_form_with_dates():
    content = json.dumps(
        {"destination": HAI_PHONG, "start_date": "2026-12-01", "end_date": "2026-12-03"}
    )
    assert (
        message_for_model(row("created_trip", content))
        == "[trip form: Hải Phòng, 2026-12-01 to 2026-12-03, created]"
    )


def test_form_without_destination_uses_question_mark():
    assert message_for_model(row("canceled_trip", "{}")) == "[trip form: ?, no dates, canceled]"


def test_broken_json_gives_bare_marker():
    for intent in sorted(TRIP_FORM_INTENTS):
        assert message_for_model(row(intent, "not json")) == "[trip form]"
    assert message_for_model(row("trip_form", "[1, 2]")) == "[trip form]"
