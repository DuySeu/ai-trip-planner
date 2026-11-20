from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from openrouter import errors

from core.constants import ModelId
from core.exceptions import LLMBudgetExceeded, LLMUnavailable, QuotaExhausted
from models.base import LLMProvider, StreamChunk
from models.model_router import (
    CallBudget,
    CallContext,
    ModelRouter,
    Purpose,
    RouterProvider,
    classify_error,
)
from tests.fakes import FakeProvider, FakeSink

PATTERN = "free-models-per-day"
NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
MODEL_A = ModelId.GEMMA_4_31B_IT
MODEL_B = ModelId.NEMOTRON_3_SUPER_120B_A12B
MESSAGES = [{"role": "user", "content": "hi"}]


# An SDK 429 built the way the SDK builds it from a JSON body
def rate_limit(message: str = "Rate limit exceeded") -> errors.TooManyRequestsResponseError:
    body = json.dumps({"error": {"code": 429, "message": message}})
    response = httpx.Response(429, text=body, headers={"content-type": "application/json"})
    data = errors.TooManyRequestsResponseErrorData.model_validate_json(body)
    return errors.TooManyRequestsResponseError(data, response, body)


# The SDK's generic error for a status without a specific class
def http_error(status: int) -> errors.OpenRouterDefaultError:
    return errors.OpenRouterDefaultError("API error occurred", httpx.Response(status, text="oops"))


# A provider that streams some text and then fails
class BrokenStream(LLMProvider):
    def __init__(self, first: str, error: Exception) -> None:
        super().__init__("fake/broken", {})
        self.first = first
        self.error = error

    # Not used by the stream tests
    def invoke(self, messages: Any, system_prompt: str, tools: Any = None) -> Any:
        raise AssertionError("invoke is not expected")

    # Yield one chunk, then raise
    def invoke_stream(self, messages: Any, system_prompt: str, tools: Any = None) -> Iterator[Any]:
        yield StreamChunk(delta=self.first)
        raise self.error


def make_router(
    providers: Mapping[str, LLMProvider],
    sink: FakeSink | None = None,
    models: Sequence[str] | None = None,
) -> tuple[ModelRouter, FakeSink]:
    sink = sink or FakeSink()
    chain: Mapping[Purpose, Sequence[str]] = {"generate": list(models or providers), "answer": []}
    router = ModelRouter(
        provider_for=lambda model_id: providers[model_id],
        models=chain,
        sink=sink,
        daily_cap_pattern=PATTERN,
        reset_hour_utc=0,
        now=lambda: NOW,
    )
    return router, sink


def test_classify_error_maps_sdk_and_network_errors():
    assert classify_error(rate_limit(), PATTERN) == "rate_limited"
    assert (
        classify_error(rate_limit("Rate limit: free-models-per-day"), PATTERN) == "quota_exhausted"
    )
    assert classify_error(http_error(502), PATTERN) == "provider_error"
    assert classify_error(http_error(408), PATTERN) == "timeout"
    assert classify_error(errors.NoResponseError(), PATTERN) == "provider_error"
    assert classify_error(httpx.ReadTimeout("slow"), PATTERN) == "timeout"
    assert classify_error(httpx.ConnectError("down"), PATTERN) == "provider_error"


def test_models_for_drops_ids_not_in_model_id():
    router, _ = make_router({MODEL_A: FakeProvider([]), "made/up:free": FakeProvider([])})
    assert router.models_for("generate") == [MODEL_A]
    assert router.models_for("answer") == []


def test_invoke_falls_back_to_next_model_on_rate_limit():
    providers = {MODEL_A: FakeProvider([rate_limit()]), MODEL_B: FakeProvider(["second"])}
    router, sink = make_router(providers)
    response = router.invoke("generate", MESSAGES, "sys", CallContext())
    assert response.answer == "second"
    assert [(r.model_id, r.outcome) for r in sink.logs] == [
        (MODEL_A, "rate_limited"),
        (MODEL_B, "ok"),
    ]


def test_invoke_raises_llm_unavailable_when_every_model_fails():
    providers = {MODEL_A: FakeProvider([http_error(503)]), MODEL_B: FakeProvider([http_error(500)])}
    router, _ = make_router(providers)
    with pytest.raises(LLMUnavailable):
        router.invoke("generate", MESSAGES, "sys", CallContext())


def test_invoke_raises_llm_unavailable_when_purpose_has_no_model():
    router, _ = make_router({MODEL_A: FakeProvider([])})
    with pytest.raises(LLMUnavailable):
        router.invoke("answer", MESSAGES, "sys", CallContext())


def test_daily_cap_blocks_service_until_next_reset_and_raises():
    provider = FakeProvider([rate_limit("free-models-per-day exhausted")])
    router, sink = make_router({MODEL_A: provider, MODEL_B: FakeProvider(["unused"])})
    with pytest.raises(QuotaExhausted) as raised:
        router.invoke("generate", MESSAGES, "sys", CallContext())
    until = datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
    assert raised.value.blocked_until == until
    assert sink.blocked_until("openrouter") == until
    assert [r.outcome for r in sink.logs] == ["quota_exhausted"]


def test_next_reset_is_strictly_after_now_when_now_is_the_reset_hour():
    provider = FakeProvider([rate_limit("free-models-per-day")])
    router = ModelRouter(
        provider_for=lambda _: provider,
        models={"generate": [MODEL_A]},
        sink=FakeSink(),
        daily_cap_pattern=PATTERN,
        reset_hour_utc=15,
        now=lambda: NOW,
    )
    with pytest.raises(QuotaExhausted) as raised:
        router.invoke("generate", MESSAGES, "sys", CallContext())
    assert raised.value.blocked_until == datetime(2026, 11, 17, 15, 0, tzinfo=UTC)


def test_active_block_raises_quota_exhausted_without_calling_provider():
    provider = FakeProvider(["never"])
    router, sink = make_router({MODEL_A: provider})
    until = datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
    sink.block("openrouter", until, "cap")
    with pytest.raises(QuotaExhausted) as raised:
        router.invoke("generate", MESSAGES, "sys", CallContext())
    assert raised.value.blocked_until == until
    assert provider.calls == []


def test_expired_block_is_ignored():
    router, sink = make_router({MODEL_A: FakeProvider(["fine"])})
    sink.block("openrouter", datetime(2026, 11, 16, 14, 0, tzinfo=UTC), "old")
    assert router.invoke("generate", MESSAGES, "sys", CallContext()).answer == "fine"


def test_budget_take_raises_after_limit_and_counts_failed_calls():
    budget = CallBudget(limit=2, used=0)
    providers = {MODEL_A: FakeProvider([http_error(500), "ok", "never"])}
    router, _ = make_router(providers)
    ctx = CallContext(budget=budget)
    with pytest.raises(LLMUnavailable):
        router.invoke_model(MODEL_A, "generate", MESSAGES, "sys", ctx)
    assert budget.used == 1
    router.invoke_model(MODEL_A, "generate", MESSAGES, "sys", ctx)
    assert budget.used == 2
    with pytest.raises(LLMBudgetExceeded):
        router.invoke_model(MODEL_A, "generate", MESSAGES, "sys", ctx)
    assert budget.used == 2
    assert len(providers[MODEL_A].calls) == 2


def test_every_call_is_logged_with_outcome_and_tokens():
    router, sink = make_router({MODEL_A: FakeProvider(["hello"])})
    ids = CallContext(trip_id=None, conversation_id=None, message_id=None)
    router.invoke("generate", MESSAGES, "sys", ids)
    (record,) = sink.logs
    assert (record.purpose, record.model_id, record.outcome) == ("generate", MODEL_A, "ok")
    assert (record.input_tokens, record.output_tokens) == (10, 5)
    assert record.latency_ms is not None and record.latency_ms >= 0
    assert record.error is None


def test_every_call_writes_one_log_line_naming_the_step_model_and_outcome(caplog):
    providers = {MODEL_A: FakeProvider([rate_limit()]), MODEL_B: FakeProvider(["second"])}
    router, _ = make_router(providers)
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


def test_failed_call_log_keeps_error_text_without_prompt():
    router, sink = make_router({MODEL_A: FakeProvider([http_error(502)])})
    with pytest.raises(LLMUnavailable):
        router.invoke("generate", MESSAGES, "secret prompt", CallContext())
    (record,) = sink.logs
    assert record.outcome == "provider_error"
    assert record.error is not None and "502" in record.error
    assert "secret prompt" not in record.error


def test_stream_yields_text_chunks():
    router, sink = make_router({MODEL_A: FakeProvider(["a long streamed answer"])})
    chunks = list(router.stream("generate", MESSAGES, "sys", CallContext()))
    assert len(chunks) > 1
    assert "".join(chunks) == "a long streamed answer"
    assert [r.outcome for r in sink.logs] == ["ok"]


def test_stream_falls_back_before_first_token_only():
    providers = {MODEL_A: FakeProvider([rate_limit()]), MODEL_B: FakeProvider(["from b"])}
    router, _ = make_router(providers)
    assert "".join(router.stream("generate", MESSAGES, "sys", CallContext())) == "from b"

    broken = {MODEL_A: BrokenStream("part ", http_error(502)), MODEL_B: FakeProvider(["from b"])}
    router, sink = make_router(broken)
    seen: list[str] = []
    with pytest.raises(LLMUnavailable):
        for chunk in router.stream("generate", MESSAGES, "sys", CallContext()):
            seen.append(chunk)
    assert seen == ["part "]
    assert [r.model_id for r in sink.logs] == [MODEL_A]


def test_stream_daily_cap_blocks_and_raises():
    router, sink = make_router({MODEL_A: FakeProvider([rate_limit("free-models-per-day")])})
    with pytest.raises(QuotaExhausted):
        list(router.stream("generate", MESSAGES, "sys", CallContext()))
    assert sink.blocked_until("openrouter") == datetime(2026, 11, 17, 0, 0, tzinfo=UTC)


def test_router_provider_goes_through_fallback_and_logging():
    providers = {MODEL_A: FakeProvider([rate_limit()]), MODEL_B: FakeProvider(["routed"])}
    router, sink = make_router(providers)
    adapter = RouterProvider(router, "generate", CallContext())
    response = adapter.invoke(MESSAGES, "sys")
    assert response.answer == "routed"
    assert adapter.model_id == MODEL_B
    assert len(sink.logs) == 2


def test_router_provider_streams_text_deltas():
    router, _ = make_router({MODEL_A: FakeProvider(["streamed text"])})
    adapter = RouterProvider(router, "generate", CallContext())
    assert "".join(c.delta or "" for c in adapter.invoke_stream(MESSAGES, "sys")) == "streamed text"
