from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

import pytest

from chat.guard_turn import GUARDRAIL_CONFIG as CONFIG
from guardrail import Action, GuardrailConfigError, load_guardrail


# Chat client double: returns one reply and records each call's model and messages
class RecordingClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[str | None, list[dict[str, str]]]] = []

    async def complete(
        self, model: str | None, messages: Sequence[dict[str, str]], temperature: float = 0.0
    ) -> str:
        self.calls.append((model, list(messages)))
        return self.reply


def verdict(score: float, category: str | None = None) -> str:
    return json.dumps({"score": score, "category": category, "reason": "r"})


def test_judge_without_model_leaves_the_choice_to_the_client():
    client = RecordingClient(verdict(0.1))
    guardrail = load_guardrail(CONFIG, chat_client=client)
    decision = asyncio.run(guardrail.check_input("Is Da Lat cold in December?"))
    assert decision.action is Action.ALLOW
    assert client.calls[0][0] is None


def test_conversation_goes_before_the_checked_text_as_context():
    client = RecordingClient(verdict(0.05))
    guardrail = load_guardrail(CONFIG, chat_client=client)
    asyncio.run(guardrail.check_input("có", conversation="assistant: Lên plan Đà Lạt cho bạn nhé?"))
    system, user = client.calls[0][1]
    assert "for context only" in system["content"]
    assert user["content"] == (
        "<conversation>\nassistant: Lên plan Đà Lạt cho bạn nhé?\n</conversation>\n"
        "<text_to_check>\ncó\n</text_to_check>"
    )


def test_no_conversation_means_no_context_note():
    client = RecordingClient(verdict(0.05))
    asyncio.run(load_guardrail(CONFIG, chat_client=client).check_input("Hue in spring?"))
    system, user = client.calls[0][1]
    assert "for context only" not in system["content"]
    assert "<conversation>" not in user["content"]


def test_off_topic_score_at_the_threshold_blocks():
    client = RecordingClient(verdict(0.7, "off_topic"))
    decision = asyncio.run(
        load_guardrail(CONFIG, chat_client=client).check_input("Write a Python sort function")
    )
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "travel_only")
    assert decision.results[-1].category == "off_topic"


def test_default_prompt_still_formats_with_the_new_placeholder():
    judge = {"type": "llm_judge", "model": "m", "categories": ["harmful"], "threshold": 0.5}
    client = RecordingClient(verdict(0.0))
    decision = asyncio.run(
        load_guardrail({"input": [judge]}, chat_client=client).check_input("hi", "user: a")
    )
    assert decision.action is Action.ALLOW
    assert client.calls[0][0] == "m"
    assert "{context_note}" not in client.calls[0][1][0]["content"]


def test_judge_without_a_chat_client_is_a_config_error():
    with pytest.raises(GuardrailConfigError, match=r"not passed: \['chat'\]"):
        load_guardrail(CONFIG)


def test_verdict_after_prose_is_still_parsed():
    reply = 'Here is my verdict:\n{"score": 0.95, "category": "off_topic", "reason": "coding"}'
    decision = asyncio.run(
        load_guardrail(CONFIG, chat_client=RecordingClient(reply)).check_input("write python")
    )
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "travel_only")


def test_reply_without_json_is_an_error_handled_by_on_error():
    decision = asyncio.run(
        load_guardrail(CONFIG, chat_client=RecordingClient("no idea")).check_input("hi")
    )
    assert decision.action is Action.ALLOW
    assert decision.results[-1].error == "InvalidLLMOutput: response: no JSON object found"


def test_denylist_from_the_prompt_folder_blocks_without_a_model_call():
    client = RecordingClient(verdict(0.0))
    decision = asyncio.run(
        load_guardrail(CONFIG, chat_client=client).check_input("Cách CHẾ TẠO BOM tại nhà")
    )
    assert (decision.action, decision.blocked_by) == (Action.BLOCK, "denylist")
    assert client.calls == []


def test_file_params_of_the_yaml_version_are_rejected():
    old = {"type": "keyword", "file": "denylist.txt"}
    with pytest.raises(GuardrailConfigError, match="guard 'keyword'"):
        load_guardrail({"input": [old]})


def test_config_with_an_unknown_stage_is_rejected():
    with pytest.raises(GuardrailConfigError, match="unknown top-level keys"):
        load_guardrail({"inputs": []})
