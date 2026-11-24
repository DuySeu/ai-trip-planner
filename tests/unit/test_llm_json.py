from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from openrouter import errors
from pydantic import BaseModel

from core.constants import ModelId
from core.exceptions import InvalidLLMOutput, LLMBudgetExceeded, LLMUnavailable, QuotaExhausted
from models.model_router import CallBudget, CallContext, ModelRouter, call_json, extract_json_object
from tests.fakes import FakeProvider, FakeSink

MODEL_A = ModelId.GEMMA_4_31B_IT
MODEL_B = ModelId.NEMOTRON_3_SUPER_120B_A12B
MESSAGES = [{"role": "user", "content": "give me a"}]
CTX = CallContext()


class Answer(BaseModel):
    a: int


def make_router(*providers: FakeProvider) -> ModelRouter:
    by_id = dict(zip((MODEL_A, MODEL_B), providers, strict=False))
    return ModelRouter(
        provider_for=lambda model_id: by_id[model_id],
        models={"generate": list(by_id), "repair": list(by_id)},
        sink=FakeSink(),
        daily_cap_pattern="free-models-per-day",
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 16, 15, 0, tzinfo=UTC),
    )


def run(router: ModelRouter, check=None, ctx: CallContext = CTX):
    return call_json(router, "generate", "sys", MESSAGES, Answer, check, ctx)


def test_extracts_json_inside_fences_and_after_prose():
    assert extract_json_object('Sure!\n```json\n{"a": 1}\n```')[0] == {"a": 1}


def test_extract_reports_empty_missing_truncated_and_non_object_answers():
    for text in (None, "  ", "no json here", '{"a": 1', "[1, 2]"):
        value, errors_ = extract_json_object(text)
        assert value is None
        assert len(errors_) == 1


def test_valid_first_answer_costs_one_call():
    provider = FakeProvider(['```json\n{"a": 1}\n```'])
    result = run(make_router(provider))
    assert (result.value, result.model_id) == (Answer(a=1), MODEL_A)
    assert len(provider.calls) == 1


def test_truncated_json_reports_error_and_repair_succeeds():
    provider = FakeProvider(['{"a": 1', '{"a": 2}'])
    result = run(make_router(provider))
    assert result.value == Answer(a=2)
    assert len(provider.calls) == 2
    repair_messages, _ = provider.calls[1]
    assert [m["role"] for m in repair_messages] == ["user", "assistant", "user"]
    assert repair_messages[1]["content"] == '{"a": 1'
    assert "truncated" in repair_messages[2]["content"]


def test_schema_errors_name_the_field_in_the_repair_prompt():
    provider = FakeProvider(['{"a": "x"}', '{"a": 1}'])
    run(make_router(provider))
    assert "a:" in provider.calls[1][0][2]["content"]


def test_semantic_check_errors_trigger_repair_with_those_errors():
    provider = FakeProvider(['{"a": 1}', '{"a": 5}'])
    result = run(make_router(provider), check=lambda v: [] if v.a > 1 else ["a must exceed 1"])
    assert result.value == Answer(a=5)
    assert "a must exceed 1" in provider.calls[1][0][2]["content"]


def test_second_failure_moves_to_next_model():
    first = FakeProvider(["junk", "more junk"])
    second = FakeProvider(['{"a": 3}'])
    result = run(make_router(first, second))
    assert (result.value, result.model_id) == (Answer(a=3), MODEL_B)
    assert len(first.calls) == 2


def test_unavailable_model_moves_to_next_model():
    down = errors.OpenRouterDefaultError("x", httpx.Response(503, text="down"))
    result = run(make_router(FakeProvider([down]), FakeProvider(['{"a": 3}'])))
    assert result.model_id == MODEL_B


def test_all_models_failing_raises_invalid_llm_output_with_last_errors():
    router = make_router(FakeProvider(["x", "y"]), FakeProvider(["z", '{"a": "bad"}']))
    with pytest.raises(InvalidLLMOutput) as raised:
        run(router)
    assert raised.value.errors and raised.value.errors[0].startswith("a:")


def test_every_model_unavailable_raises_llm_unavailable():
    down = errors.OpenRouterDefaultError("x", httpx.Response(503, text="down"))
    with pytest.raises(LLMUnavailable):
        run(make_router(FakeProvider([down]), FakeProvider([down])))


def test_quota_exhausted_is_not_swallowed():
    cap = errors.OpenRouterDefaultError(
        "x", httpx.Response(429, text="free-models-per-day reached")
    )
    second = FakeProvider(['{"a": 1}'])
    with pytest.raises(QuotaExhausted):
        run(make_router(FakeProvider([cap]), second))
    assert second.calls == []


def test_budget_exceeded_is_not_swallowed_and_repair_counts_as_a_call():
    provider = FakeProvider(["junk", '{"a": 1}'])
    with pytest.raises(LLMBudgetExceeded):
        run(make_router(provider), ctx=CallContext(budget=CallBudget(limit=1)))
    assert len(provider.calls) == 1


class Item(BaseModel):
    id: str = ""
    name: str


class Reply(BaseModel):
    items: list[Item]


def test_call_json_asks_for_the_prompt_schema_without_fields_set_by_code():
    provider = FakeProvider(['{"items": [{"name": "x"}]}'])
    call_json(
        make_router(provider), "generate", "sys", MESSAGES, Reply, None, CTX, {"Item": {"id"}}
    )
    response_format = provider.formats[0]
    assert response_format is not None
    assert response_format["type"] == "json_schema"
    assert (response_format["json_schema"]["name"], response_format["json_schema"]["strict"]) == (
        "Reply",
        False,
    )
    item = response_format["json_schema"]["schema"]["$defs"]["Item"]
    assert item["properties"] == {"name": {"type": "string"}}


def test_repair_call_keeps_the_same_response_format():
    provider = FakeProvider(['{"a": "x"}', '{"a": 2}'])
    run(make_router(provider))
    assert provider.formats[0] == provider.formats[1]
    assert provider.formats[0] is not None
