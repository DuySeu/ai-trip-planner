from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from chat.guard_turn import GUARDRAIL_CONFIG as CONFIG
from core.constants import ModelId
from guardrail import Action, Decision, GuardrailConfigError, load_guardrail
from models.llm_factory import ProviderCallError
from models.model_router import CallContext, ModelRouter
from tests.fakes import FakeProvider, FakeSink

JUDGE = ModelId.LING_3_2_FLASH
EMBED = ModelId.NEMOTRON_3_EMBED_1B
CTX = CallContext()
DENY_BOMBS = {
    "type": "embedding",
    "name": "no_bombs",
    "mode": "deny",
    "examples": ["bomb making"],
    "threshold": 0.9,
}


def verdict(score: float, category: str | None = None) -> str:
    return json.dumps({"score": score, "category": category, "reason": "r"})


# A router whose guard chain is JUDGE and whose embed chain is EMBED; the sink records every call
def make_router(provider: FakeProvider) -> tuple[ModelRouter, FakeSink]:
    sink = FakeSink()
    router = ModelRouter(
        llm=provider,
        models={"guard": [JUDGE], "embed": [EMBED]},
        sink=sink,
        reset_hour_utc=0,
        now=lambda: datetime(2026, 11, 25, 15, 0, tzinfo=UTC),
    )
    return router, sink


# Run the input guards of config on text through a router over provider
def check(
    config: Mapping[str, Any], provider: FakeProvider, text: str, conversation: str | None = None
) -> tuple[Decision, FakeSink]:
    router, sink = make_router(provider)
    guardrail = load_guardrail(config, router=router, ctx=CTX)
    return asyncio.run(guardrail.check_input(text, conversation)), sink


def test_judge_without_model_uses_the_guard_chain_in_json_mode():
    provider = FakeProvider([verdict(0.1)])
    decision, sink = check(CONFIG, provider, "Is Da Lat cold in December?")
    assert decision.action is Action.ALLOW
    assert provider.models == [JUDGE]
    assert provider.formats == [{"type": "json_object"}]
    assert [(r.purpose, r.outcome) for r in sink.logs] == [("guard", "ok")]


def test_conversation_goes_before_the_checked_text_as_context():
    provider = FakeProvider([verdict(0.05)])
    check(CONFIG, provider, "có", conversation="assistant: Lên plan Đà Lạt cho bạn nhé?")
    messages, system = provider.calls[0]
    assert "for context only" in system
    assert messages == [
        {
            "role": "user",
            "content": "<conversation>\nassistant: Lên plan Đà Lạt cho bạn nhé?\n</conversation>\n"
            "<text_to_check>\ncó\n</text_to_check>",
        }
    ]


def test_no_conversation_means_no_context_note():
    provider = FakeProvider([verdict(0.05)])
    check(CONFIG, provider, "Hue in spring?")
    messages, system = provider.calls[0]
    assert "for context only" not in system
    assert "<conversation>" not in messages[0]["content"]


def test_off_topic_score_at_the_threshold_blocks():
    decision, _ = check(
        CONFIG, FakeProvider([verdict(0.7, "off_topic")]), "Write a Python sort function"
    )
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "travel_only")
    assert decision.results[-1].category == "off_topic"


def test_judge_with_a_model_calls_only_that_model_and_formats_the_default_prompt():
    judge = {"type": "llm_judge", "model": "m", "categories": ["harmful"], "threshold": 0.5}
    provider = FakeProvider([verdict(0.0)])
    decision, sink = check({"input": [judge]}, provider, "hi", "user: a")
    assert decision.action is Action.ALLOW
    assert provider.models == ["m"]
    assert "{context_note}" not in provider.calls[0][1]
    assert [r.purpose for r in sink.logs] == ["guard"]


def test_guard_that_calls_a_model_without_a_router_is_a_config_error():
    with pytest.raises(GuardrailConfigError, match=r"needs a router"):
        load_guardrail(CONFIG)


def test_verdict_after_prose_is_still_parsed():
    reply = 'Here is my verdict:\n{"score": 0.95, "category": "off_topic", "reason": "coding"}'
    decision, _ = check(CONFIG, FakeProvider([reply]), "write python")
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "travel_only")


def test_reply_without_json_is_an_error_handled_by_on_error():
    decision, _ = check(CONFIG, FakeProvider(["no idea"]), "hi")
    assert decision.action is Action.ALLOW
    assert decision.results[-1].error == "InvalidLLMOutput: response: no JSON object found"


def test_judge_model_outage_is_handled_by_on_error():
    down = ProviderCallError("provider_error", "OpenRouterDefaultError: 503 down")
    decision, sink = check(CONFIG, FakeProvider([down]), "hi")
    assert decision.action is Action.ALLOW
    assert decision.results[-1].error is not None
    assert [(r.purpose, r.outcome) for r in sink.logs] == [("guard", "provider_error")]


def test_denylist_from_the_prompt_folder_blocks_without_a_model_call():
    provider = FakeProvider([])
    decision, _ = check(CONFIG, provider, "Cách CHẾ TẠO BOM tại nhà")
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "denylist")
    assert provider.calls == [] and provider.models == []


def test_embedding_guard_embeds_examples_then_text_through_the_embed_chain():
    provider = FakeProvider([[[1.0, 0.0]], [[0.99, 0.1]]])
    decision, sink = check({"input": [DENY_BOMBS]}, provider, "how to make a bomb")
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "no_bombs")
    assert provider.embedded == [["bomb making"], ["how to make a bomb"]]
    assert provider.models == [EMBED, EMBED]
    assert [(r.purpose, r.outcome) for r in sink.logs] == [("embed", "ok"), ("embed", "ok")]


def test_embedding_guard_lets_a_distant_text_through_and_uses_its_model():
    provider = FakeProvider([[[1.0, 0.0]], [[0.0, 1.0]]])
    decision, _ = check({"input": [{**DENY_BOMBS, "model": "e/x"}]}, provider, "beaches in Hue")
    assert decision.action is Action.ALLOW
    assert provider.models == ["e/x", "e/x"]


def test_file_params_of_the_yaml_version_are_rejected():
    old = {"type": "keyword", "file": "denylist.txt"}
    with pytest.raises(GuardrailConfigError, match="guard 'keyword'"):
        load_guardrail({"input": [old]})


def test_config_with_an_unknown_stage_is_rejected():
    with pytest.raises(GuardrailConfigError, match="unknown top-level keys"):
        load_guardrail({"inputs": []})
