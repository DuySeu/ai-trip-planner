"""Builders shared by the API and the worker, so both route LLM calls the same way."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from psycopg_pool import ConnectionPool

from core.config import config
from core.settings import Settings
from db.call_sink import DbCallSink
from models.llm_factory import LLMProvider
from models.model_router import ModelRouter, Purpose
from models.provider import BedrockProvider, OpenAIProvider, OpenRouterProvider

# Purposes that write or fix a whole plan get the planner timeout; the rest get the chat timeout
PLANNER_PURPOSES: frozenset[Purpose] = frozenset({"generate", "repair", "edit"})


# The one provider of the process, picked by LLM_PROVIDER (load_settings checked the value and key)
def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        return OpenAIProvider(config.OPENAI_API_KEY)
    if settings.llm_provider == "bedrock":
        return BedrockProvider(
            region=config.AWS_REGION,
            access_key=config.AWS_ACCESS_KEY_ID,
            secret_key=config.AWS_SECRET_ACCESS_KEY,
            role_arn=config.AWS_ROLE_ARN,
            read_timeout_s=settings.planner_timeout_s,
            max_tokens=settings.max_output_tokens,
        )
    return OpenRouterProvider(config.OPENROUTER_API_KEY, settings.openrouter_daily_cap_pattern)


# The model router: one provider, fallback chains from settings, calls and quota blocks in the database
def build_router(
    settings: Settings, pool: ConnectionPool, now: Callable[[], datetime]
) -> ModelRouter:
    models: dict[Purpose, tuple[str, ...]] = {
        "generate": settings.planner_models,
        "repair": settings.planner_models,
        "edit": settings.planner_models,
        "classify": settings.classifier_models,
        "answer": settings.chat_models,
        "discover": settings.chat_models,
        "suggest": settings.chat_models,
        "guard": settings.classifier_models,
        "embed": settings.embedding_models,
    }
    timeouts: dict[Purpose, float] = {
        purpose: settings.planner_timeout_s
        if purpose in PLANNER_PURPOSES
        else settings.chat_timeout_s
        for purpose in models
    }
    return ModelRouter(
        llm=build_llm(settings),
        models=models,
        sink=DbCallSink(pool),
        reset_hour_utc=settings.quota_reset_hour_utc,
        now=now,
        timeouts=timeouts,
    )
