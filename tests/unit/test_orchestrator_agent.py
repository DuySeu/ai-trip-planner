from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from agents.orchestrator_agent import OrchestratorAgent
from core.constants import ModelId
from models.llm_factory import ProviderCallError
from models.model_router import CallContext, ModelRouter
from orchestration.routing_schema import AgentSpec
from tests.fakes import FakeProvider, FakeSink

MODEL_A = ModelId.LING_3_2_FLASH
MODEL_B = ModelId.NEMOTRON_3_5_SUPER_VL
CATALOG = [AgentSpec(name="advice", description="travel advice")]
MESSAGES = [{"role": "user", "content": "hi"}]


# The classifier's JSON for one routed step
def route_json(agent: str) -> str:
    step = {"id": "s1", "agent": agent, "task": "do it"}
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


def make_router(
    provider: FakeProvider, models: Sequence[str] = (MODEL_A,)
) -> tuple[ModelRouter, FakeSink]:
    sink = FakeSink()
    router = ModelRouter(
        llm=provider,
        models={"classify": list(models)},
        sink=sink,
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 25, 15, 0, tzinfo=UTC),
    )
    return router, sink


def test_route_falls_back_then_repairs_and_reports_the_model_that_answered():
    # MODEL_A is down, MODEL_B names an unknown agent, then its repair names a catalog agent
    down = ProviderCallError("provider_error", "OpenRouterDefaultError: 503 down")
    provider = FakeProvider([down, route_json("nope"), down, route_json("advice")])
    router, sink = make_router(provider, (MODEL_A, MODEL_B))
    decision = OrchestratorAgent(router).route(MESSAGES, CATALOG, CallContext())
    assert decision.status == "routed" and decision.steps[0].agent == "advice"
    assert (decision.meta.model_id, decision.meta.attempts) == (MODEL_B, 2)
    assert [(r.purpose, r.model_id, r.outcome) for r in sink.logs] == [
        ("classify", MODEL_A, "provider_error"),
        ("classify", MODEL_B, "ok"),
        ("classify", MODEL_A, "provider_error"),
        ("classify", MODEL_B, "ok"),
    ]


def test_route_returns_fallback_when_repair_is_still_invalid():
    router, _ = make_router(FakeProvider([route_json("nope"), route_json("nope")]))
    decision = OrchestratorAgent(router).route(MESSAGES, CATALOG, CallContext())
    assert decision.status == "fallback"
    assert decision.meta.error and decision.meta.attempts == 2
