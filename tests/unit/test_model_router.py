from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from core.constants import ModelId
from core.exceptions import LLMBudgetExceeded, LLMUnavailable, QuotaExhausted
from models.llm_factory import LLMProvider, LLMResponse, ProviderCallError, StreamChunk
from models.model_router import CallBudget, CallContext, ModelRouter, Purpose
from tests.fakes import FakeProvider, FakeSink

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
MODEL_A = ModelId.GEMMA_4_31B_IT
MODEL_B = ModelId.NEMOTRON_3_SUPER_120B_A12B
MESSAGES = [{"role": "user", "content": "hi"}]


def limited() -> ProviderCallError:
    return ProviderCallError("rate_limited", "TooManyRequestsResponseError: Rate limit exceeded")


def capped() -> ProviderCallError:
    return ProviderCallError("quota_exhausted", "TooManyRequestsResponseError: free-models-per-day")


def down(status: int = 502) -> ProviderCallError:
    return ProviderCallError("provider_error", f"OpenRouterDefaultError: {status} oops")


# A provider that streams some text and then fails
class BrokenStream(LLMProvider):
    name = "openrouter"

    def __init__(self, first: str, error: Exception) -> None:
        self.first = first
        self.error = error

    # Not used by the stream tests
    def invoke(
        self, model_id: str, messages: Any, system_prompt: str, **kwargs: Any
    ) -> LLMResponse:
        raise AssertionError("invoke is not expected")

    # Yield one chunk, then raise
    def invoke_stream(
        self, model_id: str, messages: Any, system_prompt: str, **kwargs: Any
    ) -> Iterator[StreamChunk]:
        yield StreamChunk(delta=self.first)
        raise self.error


def make_router(
    provider: LLMProvider,
    sink: FakeSink | None = None,
    models: Sequence[str] = (MODEL_A, MODEL_B),
    timeouts: Mapping[Purpose, float] | None = None,
) -> tuple[ModelRouter, FakeSink]:
    sink = sink or FakeSink()
    chain: Mapping[Purpose, Sequence[str]] = {"generate": list(models), "answer": []}
    router = ModelRouter(
        llm=provider,
        models=chain,
        sink=sink,
        reset_hour_utc=0,
        now=lambda: NOW,
        timeouts=timeouts,
    )
    return router, sink


def test_models_for_drops_ids_the_provider_does_not_accept():
    router, _ = make_router(FakeProvider([], known={MODEL_A}), models=(MODEL_A, "made/up:free"))
    assert router.models_for("generate") == [MODEL_A]
    assert router.models_for("answer") == []


def test_invoke_falls_back_to_next_model_on_rate_limit():
    provider = FakeProvider([limited(), "second"])
    router, sink = make_router(provider)
    response = router.invoke("generate", MESSAGES, "sys", CallContext())
    assert response.answer == "second"
    assert provider.models == [MODEL_A, MODEL_B]
    assert [(r.model_id, r.outcome) for r in sink.logs] == [
        (MODEL_A, "rate_limited"),
        (MODEL_B, "ok"),
    ]


def test_invoke_raises_llm_unavailable_when_every_model_fails():
    router, _ = make_router(FakeProvider([down(503), down(500)]))
    with pytest.raises(LLMUnavailable):
        router.invoke("generate", MESSAGES, "sys", CallContext())


def test_invoke_raises_llm_unavailable_when_purpose_has_no_model():
    router, _ = make_router(FakeProvider([]))
    with pytest.raises(LLMUnavailable):
        router.invoke("answer", MESSAGES, "sys", CallContext())


def test_daily_cap_blocks_service_until_next_reset_and_raises():
    provider = FakeProvider([capped(), "unused"])
    router, sink = make_router(provider)
    with pytest.raises(QuotaExhausted) as raised:
        router.invoke("generate", MESSAGES, "sys", CallContext())
    until = datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
    assert raised.value.blocked_until == until
    assert sink.blocked_until("openrouter") == until
    assert [r.outcome for r in sink.logs] == ["quota_exhausted"]
    assert provider.models == [MODEL_A]


def test_quota_block_uses_the_provider_name():
    router, sink = make_router(FakeProvider([capped()], name="openai"))
    with pytest.raises(QuotaExhausted):
        router.invoke("generate", MESSAGES, "sys", CallContext())
    assert router.service == "openai"
    assert sink.blocked_until("openai") is not None
    assert sink.blocked_until("openrouter") is None


def test_next_reset_is_strictly_after_now_when_now_is_the_reset_hour():
    router = ModelRouter(
        llm=FakeProvider([capped()]),
        models={"generate": [MODEL_A]},
        sink=FakeSink(),
        reset_hour_utc=15,
        now=lambda: NOW,
    )
    with pytest.raises(QuotaExhausted) as raised:
        router.invoke("generate", MESSAGES, "sys", CallContext())
    assert raised.value.blocked_until == datetime(2026, 11, 17, 15, 0, tzinfo=UTC)


def test_active_block_raises_quota_exhausted_without_calling_provider():
    provider = FakeProvider(["never"])
    router, sink = make_router(provider)
    until = datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
    sink.block("openrouter", until, "cap")
    with pytest.raises(QuotaExhausted) as raised:
        router.invoke("generate", MESSAGES, "sys", CallContext())
    assert raised.value.blocked_until == until
    assert provider.calls == []


def test_expired_block_is_ignored():
    router, sink = make_router(FakeProvider(["fine"]))
    sink.block("openrouter", datetime(2026, 11, 16, 14, 0, tzinfo=UTC), "old")
    assert router.invoke("generate", MESSAGES, "sys", CallContext()).answer == "fine"


def test_budget_take_raises_after_limit_and_counts_failed_calls():
    budget = CallBudget(limit=2, used=0)
    provider = FakeProvider([down(500), "ok", "never"])
    router, _ = make_router(provider)
    ctx = CallContext(budget=budget)
    with pytest.raises(LLMUnavailable):
        router.invoke_model(MODEL_A, "generate", MESSAGES, "sys", ctx)
    assert budget.used == 1
    router.invoke_model(MODEL_A, "generate", MESSAGES, "sys", ctx)
    assert budget.used == 2
    with pytest.raises(LLMBudgetExceeded):
        router.invoke_model(MODEL_A, "generate", MESSAGES, "sys", ctx)
    assert budget.used == 2
    assert len(provider.calls) == 2


def test_router_passes_the_timeout_of_the_purpose():
    provider = FakeProvider(["a", "b"])
    router, _ = make_router(provider, timeouts={"generate": 90.0})
    router.invoke("generate", MESSAGES, "sys", CallContext())
    list(router.stream("generate", MESSAGES, "sys", CallContext()))
    assert provider.timeouts == [90.0, 90.0]


def test_purpose_without_timeout_sends_none():
    provider = FakeProvider(["a"])
    router, _ = make_router(provider)
    router.invoke("generate", MESSAGES, "sys", CallContext())
    assert provider.timeouts == [None]


def test_every_call_is_logged_with_outcome_and_tokens():
    router, sink = make_router(FakeProvider(["hello"]))
    ids = CallContext(trip_id=None, conversation_id=None, message_id=None)
    router.invoke("generate", MESSAGES, "sys", ids)
    (record,) = sink.logs
    assert (record.purpose, record.model_id, record.outcome) == ("generate", MODEL_A, "ok")
    assert (record.input_tokens, record.output_tokens) == (10, 5)
    assert record.latency_ms is not None and record.latency_ms >= 0
    assert record.error is None


def test_every_call_writes_one_log_line_naming_the_step_model_and_outcome(caplog):
    router, _ = make_router(FakeProvider([limited(), "second"]))
    with caplog.at_level(logging.INFO, logger="models.model_router"):
        router.invoke("generate", MESSAGES, "secret prompt", CallContext())
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2
    assert lines[0].startswith(
        f"llm call generate (write the trip plan) via {MODEL_A}: rate_limited"
    )
    assert lines[1].startswith(f"llm call generate (write the trip plan) via {MODEL_B}: ok")
    assert "10 in / 5 out tokens" in lines[1]
    assert caplog.records[0].levelno == logging.WARNING
    assert all("secret prompt" not in line for line in lines)


def test_failed_call_log_keeps_the_provider_error_text_without_prompt():
    router, sink = make_router(FakeProvider([down(502)]), models=(MODEL_A,))
    with pytest.raises(LLMUnavailable):
        router.invoke("generate", MESSAGES, "secret prompt", CallContext())
    (record,) = sink.logs
    assert record.outcome == "provider_error"
    assert record.error == "OpenRouterDefaultError: 502 oops"


def test_stream_yields_text_chunks():
    router, sink = make_router(FakeProvider(["a long streamed answer"]))
    chunks = list(router.stream("generate", MESSAGES, "sys", CallContext()))
    assert len(chunks) > 1
    assert "".join(chunks) == "a long streamed answer"
    assert [r.outcome for r in sink.logs] == ["ok"]


def test_stream_falls_back_before_first_token_only():
    router, _ = make_router(FakeProvider([limited(), "from b"]))
    assert "".join(router.stream("generate", MESSAGES, "sys", CallContext())) == "from b"

    router, sink = make_router(BrokenStream("part ", down(502)))
    seen: list[str] = []
    with pytest.raises(LLMUnavailable):
        for chunk in router.stream("generate", MESSAGES, "sys", CallContext()):
            seen.append(chunk)
    assert seen == ["part "]
    assert [(r.model_id, r.outcome) for r in sink.logs] == [(MODEL_A, "provider_error")]


def test_stream_daily_cap_blocks_and_raises():
    router, sink = make_router(FakeProvider([capped()]))
    with pytest.raises(QuotaExhausted):
        list(router.stream("generate", MESSAGES, "sys", CallContext()))
    assert sink.blocked_until("openrouter") == datetime(2026, 11, 17, 0, 0, tzinfo=UTC)


def test_model_without_json_support_falls_back_to_next_model():
    no_endpoints = ProviderCallError("provider_error", "NotFoundResponseError: No endpoints found")
    provider = FakeProvider([no_endpoints, '{"a": 1}'])
    router, sink = make_router(provider)
    json_object = {"type": "json_object"}
    response = router.invoke("generate", MESSAGES, "sys", CallContext(), json_object)
    assert response.answer == '{"a": 1}'
    assert provider.formats == [json_object, json_object]
    assert [(r.model_id, r.outcome) for r in sink.logs] == [
        (MODEL_A, "provider_error"),
        (MODEL_B, "ok"),
    ]


def make_embed_router(
    provider: LLMProvider, timeouts: Mapping[Purpose, float] | None = None
) -> tuple[ModelRouter, FakeSink]:
    sink = FakeSink()
    router = ModelRouter(
        llm=provider,
        models={"embed": [EMBED_A, EMBED_B]},
        sink=sink,
        reset_hour_utc=0,
        now=lambda: NOW,
        timeouts=timeouts,
    )
    return router, sink


EMBED_A = ModelId.NEMOTRON_3_EMBED_1B
EMBED_B = ModelId.LFM_2_5_EMBEDDING_350M


def test_embed_falls_back_logs_and_passes_the_embed_timeout():
    provider = FakeProvider([limited(), [[1.0, 0.0], [0.0, 1.0]]])
    router, sink = make_embed_router(provider, timeouts={"embed": 30.0})
    assert router.embed(["a", "b"], CallContext()) == [[1.0, 0.0], [0.0, 1.0]]
    assert provider.models == [EMBED_A, EMBED_B] and provider.timeouts == [30.0, 30.0]
    assert [(r.purpose, r.model_id, r.outcome, r.input_tokens) for r in sink.logs] == [
        ("embed", EMBED_A, "rate_limited", None),
        ("embed", EMBED_B, "ok", 2),
    ]


def test_embed_with_a_model_calls_only_that_model():
    provider = FakeProvider([[[1.0]]])
    router, _ = make_embed_router(provider)
    assert router.embed(["a"], CallContext(), model_id=EMBED_B) == [[1.0]]
    assert provider.models == [EMBED_B]


def test_embed_quota_blocks_and_counts_the_budget():
    budget = CallBudget(limit=5)
    router, sink = make_embed_router(FakeProvider([capped(), [[1.0]]]))
    with pytest.raises(QuotaExhausted):
        router.embed(["a"], CallContext(budget=budget))
    assert sink.blocked_until("openrouter") is not None and budget.used == 1


def test_embed_with_a_wrong_vector_count_is_invalid_output_and_falls_back():
    provider = FakeProvider([[[1.0]], [[1.0], [2.0]]])
    router, sink = make_embed_router(provider)
    assert router.embed(["a", "b"], CallContext()) == [[1.0], [2.0]]
    assert [r.outcome for r in sink.logs] == ["invalid_output", "ok"]


def test_embed_on_a_provider_without_embeddings_is_unavailable():
    router, _ = make_embed_router(BrokenStream("x", down()))
    with pytest.raises(LLMUnavailable, match="no embedding"):
        router.embed(["a"], CallContext())
