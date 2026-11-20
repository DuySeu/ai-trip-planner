from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from chat.history import message_for_model
from db.repositories.messages import MessageRow

HAI_PHONG = {"name": "Hải Phòng", "country_code": "VN", "lat": 20.86, "lon": 106.68}


def row(intent: str | None = None, content: str = "hi", metadata: Any = None) -> MessageRow:
    return MessageRow(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content=content,
        intent=intent,
        metadata=metadata,
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
    )


def form(status: str, draft: Any) -> dict[str, Any]:
    return {"status": status, "draft": draft, "trip_id": None}


def test_plain_message_is_its_content():
    assert message_for_model(row("advice", "Pack light.")) == "Pack light."
    assert message_for_model(row(None, "hello")) == "hello"


def test_open_form_names_place_and_length():
    meta = form("open", {"destination": HAI_PHONG, "length_days": 3})
    assert message_for_model(row("create_trip", "", meta)) == "[trip form: Hải Phòng, 3 days, open]"


def test_created_form_with_dates():
    draft = {"destination": HAI_PHONG, "start_date": "2026-12-01", "end_date": "2026-12-03"}
    assert (
        message_for_model(row("create_trip", "", form("created", draft)))
        == "[trip form: Hải Phòng, 2026-12-01 to 2026-12-03, created]"
    )


def test_form_without_destination_uses_question_mark():
    meta = form("canceled", {})
    assert message_for_model(row("create_trip", "", meta)) == "[trip form: ?, no dates, canceled]"


def test_form_whose_draft_is_not_an_object_gives_bare_marker():
    assert message_for_model(row("create_trip", "", form("open", [1, 2]))) == "[trip form]"
    assert message_for_model(row("create_trip", "", None)) == "[trip form]"


def test_questionnaire_card_names_what_it_has():
    meta = {"kind": "questionnaire", "status": "open", "step": 2, "answers": {"travelers": 2}}
    assert (
        message_for_model(row("discover", "", meta)) == "[questionnaire: open, answered travelers]"
    )


def test_old_questionnaire_with_text_keeps_its_text():
    meta = {"kind": "questionnaire", "status": "done", "step": 0, "answers": {}}
    assert message_for_model(row("discover", "When do you go?", meta)) == "When do you go?"
