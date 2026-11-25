from __future__ import annotations

import pytest

from core.config import config
from core.settings import load_settings
from core.wiring import build_llm
from models.provider import BedrockProvider, OpenAIProvider, OpenRouterProvider
from tests.unit.test_settings import MIN_ENV


@pytest.mark.parametrize(
    ("value", "cls"),
    [
        ("openrouter", OpenRouterProvider),
        ("openai", OpenAIProvider),
        ("bedrock", BedrockProvider),
    ],
)
def test_build_llm_makes_the_provider_named_in_settings(value, cls, monkeypatch):
    # The keys come from core.config (the process environment), like in the app
    monkeypatch.setattr(config, "OPENAI_API_KEY", "k")
    settings = load_settings({**MIN_ENV, "LLM_PROVIDER": value, "OPENAI_API_KEY": "k"})
    llm = build_llm(settings)
    assert type(llm) is cls
    assert llm.name == value


def test_bedrock_gets_the_output_token_limit_from_settings():
    env = {**MIN_ENV, "LLM_PROVIDER": "bedrock", "MAX_OUTPUT_TOKENS": "2048"}
    llm = build_llm(load_settings(env))
    assert isinstance(llm, BedrockProvider)
    assert llm._max_tokens == 2048
