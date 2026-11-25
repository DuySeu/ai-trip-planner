from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from core.constants import ModelId
from core.exceptions import InvalidLLMOutput, LLMBudgetExceeded, LLMUnavailable, QuotaExhausted
from models.llm_factory import ProviderCallError
from models.model_router import CallBudget, CallContext, ModelRouter, call_json, extract_json_object
from tests.fakes import FakeProvider, FakeSink

MODEL_A = ModelId.GEMMA_4_31B_IT
MODEL_B = ModelId.NEMOTRON_3_SUPER_120B_A12B
MESSAGES = [{"role": "user", "content": "give me a"}]
CTX = CallContext()
BOTH = (MODEL_A, MODEL_B)
DOWN = ProviderCallError("provider_error", "OpenRouterDefaultError: 503 down")


class Answer(BaseModel):
    a: int


# One provider for every model; the chain is MODEL_A, or MODEL_A then MODEL_B
def make_router(provider: FakeProvider, models: Sequence[str] = (MODEL_A,)) -> ModelRouter:
    return ModelRouter(
        llm=provider,
        models={"generate": list(models), "repair": list(models)},
        sink=FakeSink(),
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
    provider = FakeProvider(["junk", "more junk", '{"a": 3}'])
    result = run(make_router(provider, BOTH))
    assert (result.value, result.model_id) == (Answer(a=3), MODEL_B)
    assert provider.models == [MODEL_A, MODEL_A, MODEL_B]


def test_unavailable_model_moves_to_next_model():
    result = run(make_router(FakeProvider([DOWN, '{"a": 3}']), BOTH))
    assert result.model_id == MODEL_B


def test_all_models_failing_raises_invalid_llm_output_with_last_errors():
    router = make_router(FakeProvider(["x", "y", "z", '{"a": "bad"}']), BOTH)
    with pytest.raises(InvalidLLMOutput) as raised:
        run(router)
    assert raised.value.errors and raised.value.errors[0].startswith("a:")


def test_every_model_unavailable_raises_llm_unavailable():
    with pytest.raises(LLMUnavailable):
        run(make_router(FakeProvider([DOWN, DOWN]), BOTH))


def test_quota_exhausted_is_not_swallowed():
    cap = ProviderCallError("quota_exhausted", "429 free-models-per-day reached")
    provider = FakeProvider([cap, '{"a": 1}'])
    with pytest.raises(QuotaExhausted):
        run(make_router(provider, BOTH))
    assert provider.models == [MODEL_A]


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


def test_repair_call_keeps_the_timeout_of_the_original_purpose():
    provider = FakeProvider(['{"a": "x"}', '{"a": 1}'])
    router = ModelRouter(
        llm=provider,
        models={"suggest": [MODEL_A], "repair": [MODEL_A]},
        sink=FakeSink(),
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 16, 15, 0, tzinfo=UTC),
        timeouts={"suggest": 30.0, "repair": 90.0},
    )
    call_json(router, "suggest", "sys", MESSAGES, Answer, None, CTX)
    assert provider.timeouts == [30.0, 30.0]
