from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from agents.base_agent import BaseAgent
from core.constants import ModelId
from models.model_router import CallContext, ModelRouter
from tests.fakes import FakeProvider, FakeSink

MODEL = ModelId.GEMMA_4_31B_IT


class Reply(BaseModel):
    a: int
    secret: str = "set by code"


# A router whose only model answers from the provider; the sink records every call
def make_router(provider: FakeProvider) -> tuple[ModelRouter, FakeSink]:
    sink = FakeSink()
    router = ModelRouter(
        llm=provider,
        models={"answer": [MODEL], "repair": [MODEL]},
        sink=sink,
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 25, 15, 0, tzinfo=UTC),
    )
    return router, sink


def test_ask_json_formats_prompt_with_schema_without_dropped_fields():
    provider = FakeProvider(['{"a": 1}'])
    router, sink = make_router(provider)
    value = BaseAgent(router).ask_json(
        "answer", "Schema: {schema}", Reply, "hi", CallContext(), drop={"Reply": {"secret"}}
    )
    assert value == Reply(a=1)
    messages, system = provider.calls[0]
    assert system.startswith("Schema: {") and '"a"' in system and "secret" not in system
    assert messages == [{"role": "user", "content": "hi"}]
    assert [r.purpose for r in sink.logs] == ["answer"]


def test_ask_json_repairs_once_when_check_fails():
    provider = FakeProvider(['{"a": 1}', '{"a": 2}'])
    router, _ = make_router(provider)

    def check(reply: Reply) -> list[str]:
        return [] if reply.a == 2 else ["a: must be 2"]

    value = BaseAgent(router).ask_json("answer", "{schema}", Reply, "hi", CallContext(), check)
    assert value.a == 2
    assert len(provider.calls) == 2
