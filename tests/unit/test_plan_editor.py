from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.constants import ModelId
from db.repositories.messages import MessageRow
from domain.plan_edit import UpdateRequest
from models.model_router import CallContext, ModelRouter
from planning.plan_editor import compact_plan, propose_edit
from tests.fakes import FakeProvider, FakeSink
from tests.fixtures.builders import bangkok_plan, dalat_plan, dalat_request

MODEL = ModelId.GEMMA_4_31B_IT
PLAN = dalat_plan()
REQ = dalat_request()
CTX = CallContext()


# A router whose only model answers from the provider
def make_router(provider: FakeProvider) -> ModelRouter:
    return ModelRouter(
        llm=provider,
        models={"edit": [MODEL], "repair": [MODEL]},
        sink=FakeSink(),
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 16, 15, 0, tzinfo=UTC),
    )


# An edit answer as the model would write it
def answer(*ops: dict[str, Any]) -> str:
    return json.dumps({"ops": list(ops), "explanation": "Done."})


GOOD = answer({"op": "update_item", "item_id": "it_3", "changes": {"title": "Cafe by the lake"}})
UNKNOWN_ID = answer({"op": "remove_item", "item_id": "it_999"})
BACKWARDS_ITEM = answer(
    {
        "op": "add_item",
        "date": "2026-12-20",
        "item": {
            "title": "Late tea",
            "category": "food",
            "start_time": "15:00",
            "end_time": "14:00",
        },
    }
)


def test_valid_edit_is_returned_after_one_call():
    provider = FakeProvider([GOOD])
    result = propose_edit(make_router(provider), REQ, PLAN, [], "rename it_3", CTX)
    assert result.value.ops[0].op == "update_item"
    assert result.value.explanation == "Done."
    assert len(provider.calls) == 1


def test_edit_with_unknown_id_is_repaired_once():
    provider = FakeProvider([UNKNOWN_ID, GOOD])
    result = propose_edit(make_router(provider), REQ, PLAN, [], "drop it_999", CTX)
    assert result.value.ops[0].op == "update_item"
    assert len(provider.calls) == 2
    assert "unknown item id it_999" in provider.calls[1][0][-1]["content"]


def test_edit_that_breaks_plan_rules_is_repaired_once():
    provider = FakeProvider([BACKWARDS_ITEM, GOOD])
    result = propose_edit(make_router(provider), REQ, PLAN, [], "add late tea", CTX)
    assert result.value.ops[0].op == "update_item"
    assert "ends before it starts" in provider.calls[1][0][-1]["content"]


def test_request_change_edit_is_not_rule_checked_against_the_old_plan():
    change = answer({"op": "update_request", "changes": {"travelers": 3}})
    provider = FakeProvider([change])
    result = propose_edit(make_router(provider), REQ, PLAN, [], "we are 3 now", CTX)
    assert isinstance(result.value.ops[0], UpdateRequest)
    assert len(provider.calls) == 1


def test_compact_plan_shows_every_item_and_option_id():
    for plan in (PLAN, bangkok_plan()):
        text = compact_plan(plan)
        ids = [i.id for d in plan.days for i in d.items]
        ids += [o.id for o in plan.transport_options]
        ids += [a.id for a in plan.accommodation] + [c.id for c in plan.checklist]
        assert ids
        assert all(re.search(rf"^  {i}[ :]", text, re.MULTILINE) for i in ids)


def test_prompt_holds_plan_history_and_request_as_data():
    history = [
        MessageRow(uuid4(), uuid4(), "user", "earlier question", None, None, datetime.now(UTC))
    ]
    provider = FakeProvider([GOOD])
    propose_edit(make_router(provider), REQ, PLAN, history, "make dinner cheaper", CTX)
    messages, system = provider.calls[0]
    content = messages[0]["content"]
    assert "<plan>" in content and "user: earlier question" in content
    assert content.endswith("<request>\nmake dinner cheaper\n</request>")
    assert "data" in system and "Vietnamese" in system
